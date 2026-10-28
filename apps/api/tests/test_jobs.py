import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api import jobs as jobs_mod
from app.core import jobsign
from app.core.db import make_engine, scoped_connection
from app.core.security import hash_secret
from tests.conftest import JOB_SEED_B64, agent, hdr, login, snap

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "job-envelope.schema.json").read_text())


def _pub_b64():
    from cryptography.hazmat.primitives import serialization
    pub = jobsign.load_private(JOB_SEED_B64).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    import base64
    return base64.b64encode(pub).decode()


def idem():
    return {"Idempotency-Key": uuid4().hex}


@pytest.fixture(scope="module")
def targets(seed, inv):
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    a = agent(c, inv, "a1")
    c.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, name="OLT-JOB"))
    c.post("/v1/edge/cpe-snapshots", headers=a, json={"edge_id": str(inv["a1"]["edge"]), "observed_at": snap(inv)["observed_at"], "cpes": [
        {"canonical_serial": "JOBCPE0001", "binding": {"protocol": "tr069", "external_id": "job-ext-1", "connector_id": "c-job"}}]})
    h = hdr(c, "alice", seed, "A")
    olt = next(o["id"] for o in c.get("/v1/olts", headers=h).json() if o["name"] == "OLT-JOB")
    cpe = next(x["id"] for x in c.get("/v1/cpes", headers=h).json() if x["canonical_serial"] == "JOBCPE0001")
    return {"olt": olt, "cpe": cpe}


def preview(client, headers, op, target, **kw):
    return client.post("/v1/jobs/preview", headers={**headers, **idem()}, json={"operation": op, "target_id": target, **kw})


def test_r0_collect_full_lifecycle_with_signed_envelope(client, seed, inv, targets):
    h = hdr(client, "alice", seed, "A")
    r = preview(client, h, "collect", targets["olt"])
    assert r.status_code == 201 and r.json()["status"] == "PREVIEWED" and r.json()["risk"] == "R0"
    jid = r.json()["id"]
    assert client.post(f"/v1/jobs/{jid}/submit", headers=h).json()["status"] == "APPROVED"  # R0: no approval needed
    a = agent(client, inv, "a1")
    env = client.get("/v1/edge/jobs/next", headers=a)
    assert env.status_code == 200
    env = env.json()
    assert not list(Draft202012Validator(SCHEMA).iter_errors(env)), "envelope must match contracts/job-envelope.schema.json"
    assert jobsign.verify(_pub_b64(), env)
    assert env["operation"] == "collect" and env["edge_id"] == str(inv["a1"]["edge"]) and env["tenant_id"] == str(seed["A"])
    tampered = {**env, "operation": "reboot_cpe"}
    assert not jobsign.verify(_pub_b64(), tampered)  # any field change invalidates the signature
    assert client.get("/v1/edge/jobs/next", headers=a).status_code == 204  # dispatched once only
    done = client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": "accepted"})
    assert done.status_code == 204
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": "succeeded", "postcheck_ok": True}).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "SUCCEEDED"


def test_success_without_postcheck_is_unknown_not_succeeded(client, seed, inv, targets):
    h = hdr(client, "alice", seed, "A")
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    a = agent(client, inv, "a1")
    client.get("/v1/edge/jobs/next", headers=a)
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": "succeeded"}).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "UNKNOWN"


@pytest.mark.parametrize("op,target", [("reboot_cpe", "cpe"), ("set_wifi_ssid", "cpe"), ("provision_onu", "olt")])
def test_write_operations_are_blocked_until_homologated(client, seed, inv, targets, op, target):
    h = hdr(client, "alice", seed, "A")
    r = preview(client, h, op, targets[target])
    assert r.status_code == 201 and r.json()["blocked_reason"] == "operation_not_homologated"
    jid = r.json()["id"]
    s = client.post(f"/v1/jobs/{jid}/submit", headers=h)
    assert s.status_code == 409 and "homologated" in s.json()["detail"]
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "PREVIEWED"
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204  # nothing to dispatch


def test_gate_logic_for_approvals_when_a_write_op_is_homologated(client, seed, inv, targets, monkeypatch):
    """Simulates a FUTURE homologation to prove the approval rules (not enabled in this build)."""
    monkeypatch.setattr(jobs_mod, "HOMOLOGATED_WRITES", frozenset({"set_wifi_ssid", "provision_onu"}))
    ha, hb = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")
    # R2: engineer-level requester cannot be their own approver; needs ONE distinct approver with jobs:approve
    jid = preview(client, ha, "set_wifi_ssid", targets["cpe"]).json()["id"]
    assert client.post(f"/v1/jobs/{jid}/submit", headers=ha).json()["status"] == "PENDING_APPROVAL"
    assert client.post(f"/v1/jobs/{jid}/approve", headers=ha).status_code == 403  # self approval refused
    assert client.post(f"/v1/jobs/{jid}/approve", headers=hb).status_code == 403   # noc_n1 lacks jobs:approve
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204  # not approved => not dispatched


def test_two_person_rule_for_r3(client, seed, inv, targets, monkeypatch, migrated):
    monkeypatch.setattr(jobs_mod, "HOMOLOGATED_WRITES", frozenset({"provision_onu"}))
    ha = hdr(client, "alice", seed, "A")
    with migrated.begin() as c:  # second approver in tenant A: promote a fresh admin
        uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES ('admin2@example.com','Admin2',:h) RETURNING id"),
                        {"h": hash_secret("correct horse battery")}).scalar()
        c.execute(text("INSERT INTO tenant_memberships VALUES (:t,:u,'isp_admin')"), {"t": seed["A"], "u": uid})
    h2 = {**login_as(client, "admin2@example.com"), "X-Workspace-ID": str(seed["A"])}
    eng = {**login(client, "carol"), "X-Workspace-ID": str(seed["A"])}  # auditor in A: cannot request
    assert client.post("/v1/jobs/preview", headers={**eng, **idem()}, json={"operation": "collect", "target_id": targets["olt"]}).status_code == 403
    jid = preview(client, ha, "provision_onu", targets["olt"]).json()["id"]
    assert client.post(f"/v1/jobs/{jid}/submit", headers=ha).json()["required_approvals"] == 2
    first = client.post(f"/v1/jobs/{jid}/approve", headers=h2)
    assert first.status_code == 200 and first.json()["status"] == "PENDING_APPROVAL"       # 1 of 2 is not enough
    assert client.post(f"/v1/jobs/{jid}/approve", headers=h2).status_code == 409           # same approver twice refused
    h3 = {**login_as(client, "alice@example.com"), "X-Workspace-ID": str(seed["A"])}
    assert client.post(f"/v1/jobs/{jid}/approve", headers=h3).status_code == 403           # requester cannot be the 2nd approver
    with migrated.begin() as c:
        uid3 = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES ('admin3@example.com','A3',:h) RETURNING id"),
                         {"h": hash_secret("correct horse battery")}).scalar()
        c.execute(text("INSERT INTO tenant_memberships VALUES (:t,:u,'isp_admin')"), {"t": seed["A"], "u": uid3})
    h4 = {**login_as(client, "admin3@example.com"), "X-Workspace-ID": str(seed["A"])}
    done = client.post(f"/v1/jobs/{jid}/approve", headers=h4)
    assert done.status_code == 200 and done.json()["status"] == "APPROVED"                 # two distinct approvers => approved


def login_as(client, email):
    r = client.post("/v1/auth/token", json={"email": email, "password": "correct horse battery"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_illegal_transitions_rejected(client, seed, inv, targets):
    h = hdr(client, "alice", seed, "A")
    a = agent(client, inv, "a1")
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": "accepted"}).status_code == 409  # PREVIEWED -> ACCEPTED
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    assert client.post(f"/v1/jobs/{jid}/submit", headers=h).status_code == 409           # already submitted
    assert client.post(f"/v1/jobs/{jid}/cancel", headers=h).status_code == 200
    assert client.post(f"/v1/jobs/{jid}/approve", headers=h).status_code in (403, 409)    # cancelled can't be approved
    assert client.get("/v1/edge/jobs/next", headers=a).status_code == 204                 # cancelled isn't dispatched
    assert client.post(f"/v1/jobs/{jid}/cancel", headers=h).status_code == 409


def test_expired_job_is_never_dispatched(client, seed, inv, targets, migrated):
    h = hdr(client, "alice", seed, "A")
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET expires_at = now() - interval '1 minute' WHERE id=:i"), {"i": jid})
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "EXPIRED"


def test_idempotency_key_semantics(client, seed, targets):
    h = hdr(client, "alice", seed, "A")
    key = {"Idempotency-Key": uuid4().hex}
    body = {"operation": "collect", "target_id": targets["olt"]}
    a = client.post("/v1/jobs/preview", headers={**h, **key}, json=body)
    b = client.post("/v1/jobs/preview", headers={**h, **key}, json=body)
    assert a.json()["id"] == b.json()["id"]
    other = client.post("/v1/jobs/preview", headers={**h, **key}, json={"operation": "refresh", "target_id": targets["cpe"]})
    assert other.status_code == 409
    assert client.post("/v1/jobs/preview", headers=h, json=body).status_code == 422  # key mandatory


def test_input_validation_and_isolation(client, seed, inv, targets):
    h = hdr(client, "alice", seed, "A")
    assert preview(client, h, "format_disk", targets["olt"]).status_code == 422
    assert preview(client, h, "collect", targets["olt"], params={"cmd": "reboot"}).status_code == 422  # no free-form params
    assert preview(client, h, "collect", str(uuid4())).status_code == 404
    hb = hdr(client, "bob", seed, "B")
    assert preview(client, hb, "collect", targets["olt"]).status_code == 404  # other tenant's target
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]
    assert client.get(f"/v1/jobs/{jid}", headers=hb).status_code == 404
    assert client.post(f"/v1/jobs/{jid}/submit", headers=hb).status_code == 404
    assert client.get("/v1/jobs", headers=hb).json() == []


def test_other_edge_cannot_pull_or_report(client, seed, inv, targets):
    h = hdr(client, "alice", seed, "A")
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]  # target belongs to edge a1
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    a2 = agent(client, inv, "a2")
    assert client.get("/v1/edge/jobs/next", headers=a2).status_code == 204
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a2, json={"state": "failed"}).status_code == 403
    assert client.get("/v1/edge/jobs/next", headers=h).status_code == 403  # humans can't pull jobs


def test_dispatch_fails_closed_without_signing_key(client, seed, inv, targets, monkeypatch):
    from app.core import settings
    h = hdr(client, "alice", seed, "A")
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    monkeypatch.setenv("JOB_SIGNING_KEY", "")
    settings.get_settings.cache_clear()
    try:
        assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 503
    finally:
        monkeypatch.undo()
        settings.get_settings.cache_clear()


def test_runtime_role_cannot_rewrite_job_intent_or_delete(seed, app_url):
    eng = make_engine(app_url)
    for stmt in ("DELETE FROM jobs", "UPDATE jobs SET operation = 'collect'", "UPDATE jobs SET requested_by = gen_random_uuid()",
                 "DELETE FROM job_approvals", "UPDATE job_approvals SET approver_id = gen_random_uuid()"):
        with pytest.raises(DBAPIError), scoped_connection(eng, tenant_id=seed["A"]) as c:
            c.execute(text(stmt))


def test_dispatched_but_unreported_job_is_swept_to_expired(client, seed, inv, targets, migrated):
    h = hdr(client, "alice", seed, "A")
    a = agent(client, inv, "a1")
    while client.get("/v1/edge/jobs/next", headers=a).status_code == 200:  # drain jobs left by other tests
        pass
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    assert client.get("/v1/edge/jobs/next", headers=a).status_code == 200
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET expires_at = now() - interval '10 minutes' WHERE id=:i"), {"i": jid})
    client.get("/v1/edge/jobs/next", headers=a)
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "EXPIRED"


@pytest.mark.parametrize("key", ["has space 12345", "<script>alert1", "a\x7fbcdefgh"])
def test_idempotency_key_charset_is_ascii_safe_for_cross_language_signing(client, seed, targets, key):
    # HTTP header values are latin-1 on the wire, so U+2028/U+2029 cannot arrive; the strict ASCII pattern still guarantees
    # identical canonical JSON in Python and Go for every key that can be signed.
    h = hdr(client, "alice", seed, "A")
    r = client.post("/v1/jobs/preview", headers={**h, "Idempotency-Key": key}, json={"operation": "collect", "target_id": targets["olt"]})
    assert r.status_code == 422


def test_result_report_is_idempotent_for_edge_retries(client, seed, inv, targets):
    h = hdr(client, "alice", seed, "A")
    a = agent(client, inv, "a1")
    while client.get("/v1/edge/jobs/next", headers=a).status_code == 200:
        pass
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    client.get("/v1/edge/jobs/next", headers=a)
    for _ in range(2):
        assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": "accepted"}).status_code == 204
    for _ in range(3):
        assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": "succeeded", "postcheck_ok": True}).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "SUCCEEDED"
    # a DIFFERENT outcome after a terminal one is still refused
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": "failed"}).status_code == 409
