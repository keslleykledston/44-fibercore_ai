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


def test_refresh_of_a_cpe_carries_the_signed_acs_reference_and_collect_does_not(client, seed, inv, targets):
    h = hdr(client, "alice", seed, "A")
    a = agent(client, inv, "a1")
    jid = preview(client, h, "refresh", targets["cpe"]).json()["id"]
    assert client.post(f"/v1/jobs/{jid}/submit", headers=h).json()["status"] == "APPROVED"
    env = client.get("/v1/edge/jobs/next", headers=a).json()
    assert env["operation"] == "refresh" and env["target_ref"] == "job-ext-1"
    assert not list(Draft202012Validator(SCHEMA).iter_errors(env))
    assert jobsign.verify(_pub_b64(), env)
    assert not jobsign.verify(_pub_b64(), {**env, "target_ref": "other-device-1"})  # the ref is covered by the signature
    c = preview(client, h, "collect", targets["olt"]).json()["id"]
    client.post(f"/v1/jobs/{c}/submit", headers=h)
    assert "target_ref" not in client.get("/v1/edge/jobs/next", headers=a).json()


def test_refresh_without_a_tr069_binding_has_no_reference(client, seed, inv, targets, migrated):
    h = hdr(client, "alice", seed, "A")
    with migrated.begin() as c:
        c.execute(text("UPDATE cpe_protocol_bindings SET protocol = 'tr369' WHERE cpe_id = :i"), {"i": targets["cpe"]})
    try:
        jid = preview(client, h, "refresh", targets["cpe"]).json()["id"]
        client.post(f"/v1/jobs/{jid}/submit", headers=h)
        assert "target_ref" not in client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).json()
    finally:
        with migrated.begin() as c:
            c.execute(text("UPDATE cpe_protocol_bindings SET protocol = 'tr069' WHERE cpe_id = :i"), {"i": targets["cpe"]})


def test_success_without_postcheck_is_unknown_not_succeeded(client, seed, inv, targets):
    h = hdr(client, "alice", seed, "A")
    jid = preview(client, h, "collect", targets["olt"]).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    a = agent(client, inv, "a1")
    client.get("/v1/edge/jobs/next", headers=a)
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": "succeeded"}).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "UNKNOWN"


@pytest.mark.parametrize("op,target", [("reboot_cpe", "cpe"), ("provision_onu", "olt")])
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
    monkeypatch.setattr(jobs_mod.bench, "BENCH_OPS", {k: v for k, v in jobs_mod.bench.BENCH_OPS.items() if k != "set_wifi_ssid"})  # the generic R2 rules
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


def test_one_mutation_at_a_time_per_target_and_reads_never_wait(client, seed, inv, targets, monkeypatch):
    """FC22-015: a second write on the SAME target waits (stays APPROVED, never dropped) while the first is in flight; reads neither wait nor hold a write back."""
    monkeypatch.setattr(jobs_mod, "HOMOLOGATED_WRITES", frozenset({"reboot_cpe"}))
    monkeypatch.setattr(jobs_mod.bench, "BENCH_OPS", {k: v for k, v in jobs_mod.bench.BENCH_OPS.items() if k != "reboot_cpe"})  # the generic rules
    h = hdr(client, "alice", seed, "A")
    a = agent(client, inv, "a1")
    while client.get("/v1/edge/jobs/next", headers=a).status_code == 200:
        pass

    def approved(op):
        jid = preview(client, h, op, targets["cpe"]).json()["id"]
        assert client.post(f"/v1/jobs/{jid}/submit", headers=h).json()["status"] == "APPROVED"
        return jid

    first, second = approved("reboot_cpe"), approved("reboot_cpe")
    got = client.get("/v1/edge/jobs/next", headers=a)
    assert got.status_code == 200 and got.json()["job_id"] == first
    assert client.get("/v1/edge/jobs/next", headers=a).status_code == 204                   # the second waits: the first is in flight on the SAME target
    assert client.get(f"/v1/jobs/{second}", headers=h).json()["status"] == "APPROVED"       # waiting, not cancelled or expired
    read = approved("refresh")                                                              # a read on the same CPE is not held back by the write
    nxt = client.get("/v1/edge/jobs/next", headers=a)
    assert nxt.status_code == 200 and nxt.json()["job_id"] == read
    for state in ("accepted", "succeeded"):                                                 # the first finishes: the target is free again
        body = {"state": state, **({"postcheck_ok": True} if state == "succeeded" else {})}
        assert client.post(f"/v1/edge/jobs/{first}/result", headers=a, json=body).status_code == 204
    done = client.get("/v1/edge/jobs/next", headers=a)
    assert done.status_code == 200 and done.json()["job_id"] == second                      # and the waiting write is dispatched, once
    assert client.get("/v1/edge/jobs/next", headers=a).status_code == 204
    for state in ("accepted", "succeeded"):
        client.post(f"/v1/edge/jobs/{second}/result", headers=a, json={"state": state, **({"postcheck_ok": True} if state == "succeeded" else {})})
    # a write on ANOTHER target is never held back by one in flight elsewhere
    client.post("/v1/edge/cpe-snapshots", headers=a, json={"edge_id": str(inv["a1"]["edge"]), "observed_at": snap(inv)["observed_at"], "cpes": [
        {"canonical_serial": "JOBCPE0002", "binding": {"protocol": "tr069", "external_id": "job-ext-2", "connector_id": "c-job"}}]})
    other = next(x["id"] for x in client.get("/v1/cpes", headers=h).json() if x["canonical_serial"] == "JOBCPE0002")
    held = approved("reboot_cpe")                                                           # in flight on the first CPE again
    assert client.get("/v1/edge/jobs/next", headers=a).json()["job_id"] == held
    free = preview(client, h, "reboot_cpe", other).json()["id"]
    assert client.post(f"/v1/jobs/{free}/submit", headers=h).json()["status"] == "APPROVED"
    got = client.get("/v1/edge/jobs/next", headers=a)
    assert got.status_code == 200 and got.json()["job_id"] == free
    for jid in (held, free):                                                                 # leave nothing in flight for the next test
        for state in ("accepted", "succeeded"):
            assert client.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": state, **({"postcheck_ok": True} if state == "succeeded" else {})}).status_code == 204


def test_a_write_stuck_in_flight_stops_holding_the_target_after_its_window(client, seed, inv, targets, monkeypatch, migrated):
    """A lost Edge report (job stuck in ACCEPTED) must not hold the target for ever: after LIVE_FOR without moving, it no longer excludes."""
    monkeypatch.setattr(jobs_mod, "HOMOLOGATED_WRITES", frozenset({"reboot_cpe"}))
    monkeypatch.setattr(jobs_mod.bench, "BENCH_OPS", {k: v for k, v in jobs_mod.bench.BENCH_OPS.items() if k != "reboot_cpe"})
    h = hdr(client, "alice", seed, "A")
    a = agent(client, inv, "a1")
    while client.get("/v1/edge/jobs/next", headers=a).status_code == 200:
        pass

    def approved():
        jid = preview(client, h, "reboot_cpe", targets["cpe"]).json()["id"]
        assert client.post(f"/v1/jobs/{jid}/submit", headers=h).json()["status"] == "APPROVED"
        return jid

    stuck, waiting = approved(), approved()
    assert client.get("/v1/edge/jobs/next", headers=a).json()["job_id"] == stuck
    assert client.post(f"/v1/edge/jobs/{stuck}/result", headers=a, json={"state": "accepted"}).status_code == 204     # ...and then the Edge goes quiet
    assert client.get("/v1/edge/jobs/next", headers=a).status_code == 204                                             # held while it is recent
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET updated_at = now() - interval '31 minutes' WHERE id = :i"), {"i": stuck})
    got = client.get("/v1/edge/jobs/next", headers=a)
    assert got.status_code == 200 and got.json()["job_id"] == waiting                                                 # the stale one no longer holds it
    for state in ("accepted", "succeeded"):                                                                           # leave nothing in flight for the next test
        assert client.post(f"/v1/edge/jobs/{waiting}/result", headers=a, json={"state": state, **({"postcheck_ok": True} if state == "succeeded" else {})}).status_code == 204


def test_two_simultaneous_next_calls_never_dispatch_two_writes_on_one_target(seed, inv, targets, monkeypatch):
    """The race the advisory lock closes: both calls select before either dispatches. Repeated rounds, a barrier lines the two calls up."""
    import threading

    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setattr(jobs_mod, "HOMOLOGATED_WRITES", frozenset({"reboot_cpe"}))
    monkeypatch.setattr(jobs_mod.bench, "BENCH_OPS", {k: v for k, v in jobs_mod.bench.BENCH_OPS.items() if k != "reboot_cpe"})
    c0 = TestClient(app)
    h = hdr(c0, "alice", seed, "A")
    a = agent(c0, inv, "a1")
    while c0.get("/v1/edge/jobs/next", headers=a).status_code == 200:
        pass
    for _ in range(12):
        ids = []
        for _ in range(2):
            jid = preview(c0, h, "reboot_cpe", targets["cpe"]).json()["id"]
            assert c0.post(f"/v1/jobs/{jid}/submit", headers=h).json()["status"] == "APPROVED"
            ids.append(jid)
        gate, codes = threading.Barrier(2), []

        def call(gate=gate, codes=codes):
            cl = TestClient(app)
            gate.wait()
            codes.append(cl.get("/v1/edge/jobs/next", headers=a).status_code)

        ts = [threading.Thread(target=call) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert sorted(codes) == [200, 204], codes        # exactly one envelope, never two writes in flight on the same target
        sent = next(i for i in ids if c0.get(f"/v1/jobs/{i}", headers=h).json()["status"] == "DISPATCHED")
        other = next(i for i in ids if i != sent)
        assert c0.get(f"/v1/jobs/{other}", headers=h).json()["status"] == "APPROVED"
        for jid in (sent, other):                        # drain: finish the sent one, dispatch and finish the waiting one
            if jid == other:
                assert c0.get("/v1/edge/jobs/next", headers=a).json()["job_id"] == other
            for state in ("accepted", "succeeded"):
                assert c0.post(f"/v1/edge/jobs/{jid}/result", headers=a, json={"state": state, **({"postcheck_ok": True} if state == "succeeded" else {})}).status_code == 204
