"""`olt_query` (ADR-0029), cloud half: the closed intent, the gates (flag, Edge channel, rollout, permission, quota) and what the signed envelope carries.
Nothing here reaches equipment, and the channel stays refused in this build (`EDGE_SUPPORT` False) unless a test turns it on for itself."""
from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core import olt_query
from tests.conftest import agent, hdr, snap
from tests.test_jobs import _pub_b64

GO_CATALOG = Path(__file__).resolve().parents[3] / "agents" / "edge" / "internal" / "olt" / "query.go"


def _key():
    return {"Idempotency-Key": f"q-{uuid4().hex}"}


@pytest.fixture
def olt(client, seed, inv):
    name = f"OLT-Q{uuid4().hex[:6]}"
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv, name=name)).status_code == 202
    h = hdr(client, "alice", seed, "A")
    return next(o["id"] for o in client.get("/v1/olts", headers=h).json() if o["name"] == name)


@pytest.fixture
def on(migrated, seed, monkeypatch):
    """The flag on and the Edge channel 'present': the cloud half exercised on its own."""
    monkeypatch.setattr(olt_query, "EDGE_SUPPORT", True)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'olt_query',true) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = true"),
                  {"t": seed["A"]})
    yield
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM tenant_features WHERE tenant_id = :t AND feature = 'olt_query'"), {"t": seed["A"]})
        c.execute(text("DELETE FROM jobs WHERE operation = 'olt_query'"))


def _ask(client, h, olt, qid="olt.version", params=None, key=None):
    return client.post(f"/v1/olts/{olt}/queries/{qid}", headers={**h, **(key or _key())}, json={"params": params or {}})


def test_the_cloud_catalog_is_the_edge_catalog():
    src = GO_CATALOG.read_text()
    rows = re.findall(r'\{"([a-z.]+)", "[^"]*", Scope(Global|Slot|PON|ONU), "[^"]*", (true|false), "\d+"\}', src)
    assert len(rows) == len(olt_query.CATALOG) == 25
    for (qid, scope, validated), q in zip(rows, olt_query.CATALOG, strict=True):
        assert (qid, scope.lower(), validated == "true") == (q.id, q.scope, q.validated)
    gate = {"MaxSlot": "slot", "MaxPort": "port", "MaxONT": "ont"}
    for name, field in gate.items():
        m = re.search(rf"max{name[3:]}\s*=\s*(\d+)", src)
        assert m and int(m.group(1)) == olt_query.LIMITS[field]
    assert olt_query.ROLLOUT <= {q.id for q in olt_query.CATALOG if q.validated}   # only validated queries are ever offered


def test_every_scope_takes_exactly_its_fields():
    for qid, ok in [("olt.version", {}), ("slot.cpu", {"slot": 3}), ("pon.ont.info", {"slot": 1, "port": 0}), ("onu.info", {"slot": 1, "port": 0, "ont": 9})]:
        assert olt_query.check_params(qid, ok) == ok
    bad = [("olt.version", {"slot": 1}), ("slot.cpu", {}), ("slot.cpu", {"slot": 1, "port": 0}), ("pon.ont.info", {"slot": 1}), ("onu.info", {"slot": 1, "port": 0}),
           ("onu.info", {"slot": 1, "port": 0, "ont": 1, "extra": 1})]
    for qid, p in bad:
        with pytest.raises(ValueError, match="fields_do_not_match_scope"):
            olt_query.check_params(qid, p)
    for p in ({"slot": 18}, {"slot": -1}, {"slot": "1"}, {"slot": True}, {"slot": 1.5}, {"slot": None}):
        with pytest.raises(ValueError, match="parameter_out_of_range"):
            olt_query.check_params("slot.cpu", p)
    with pytest.raises(ValueError, match="unknown_query"):
        olt_query.check_params("olt.reboot", {})


def test_nothing_is_offered_nor_created_while_the_edge_channel_does_not_exist(client, seed, inv, olt, migrated):
    h = hdr(client, "alice", seed, "A")
    cat = client.get(f"/v1/olts/{olt}/queries", headers=h).json()
    assert cat["enabled"] is False and not any(i["offered"] for i in cat["items"]) and cat["catalog_version"] == olt_query.catalog_version()
    r = _ask(client, h, olt)
    assert (r.status_code, r.json()["detail"]) == (409, "olt_query_disabled")
    r = client.post("/v1/jobs/preview", headers={**h, **_key()}, json={"operation": "olt_query", "target_id": olt, "params": {"query_id": "olt.version"}})
    assert (r.status_code, r.json()["detail"]) == (409, "olt_query_disabled")   # the generic route cannot get around it
    with migrated.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query'")).scalar_one() == 0


def test_the_flag_alone_is_not_enough_and_the_cli_refuses_it(client, seed, inv, olt, migrated, monkeypatch):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'olt_query',true)"), {"t": seed["A"]})
    try:
        assert _ask(client, hdr(client, "alice", seed, "A"), olt).status_code == 409
    finally:
        with migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text("DELETE FROM tenant_features WHERE tenant_id = :t AND feature = 'olt_query'"), {"t": seed["A"]})
    from app import cli
    src = Path(cli.__file__).read_text()
    assert 'a.feature == "olt_query" and a.state == "on"' in src and "olt_query.EDGE_SUPPORT" in src


def test_a_request_becomes_a_closed_signed_intent(client, seed, inv, olt, on):
    h = hdr(client, "alice", seed, "A")
    r = _ask(client, h, olt, "olt.board")
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert r.json()["outcome"] == "submitted" and job["status"] == "APPROVED" and job["risk"] == "R0" and job["required_approvals"] == 0
    env = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    assert env.status_code == 200
    e = env.json()
    from app.core import jobsign
    assert jobsign.verify(_pub_b64(), e) and e["operation"] == "olt_query" and e["target_id"] == olt
    assert e["params"] == {"query_id": "olt.board", "olt_ref": olt, "catalog_version": olt_query.catalog_version()}
    assert jobsign.verify(_pub_b64(), {**e, "params": {**e["params"], "query_id": "olt.version"}}) is False   # the intent is covered by the signature
    from jsonschema import Draft202012Validator

    from tests.test_jobs import SCHEMA
    assert not list(Draft202012Validator(SCHEMA).iter_errors(e))


def test_gates_before_a_job_exists(client, seed, inv, olt, on, migrated):
    h = hdr(client, "alice", seed, "A")
    assert _ask(client, h, olt, "olt.version", {"slot": 1}).status_code == 422                 # a field the scope does not take
    assert _ask(client, h, olt, "olt.nothing").status_code == 422                               # not in the catalog
    assert _ask(client, h, olt, "pon.ont.info", {"slot": 1, "port": 0}).json()["detail"] == "query_not_enabled"   # validated, but not in this rollout step
    assert _ask(client, h, olt, "olt.time").json()["detail"] == "query_not_enabled"             # in the catalog, not validated
    assert _ask(client, hdr(client, "dave", seed, "A"), olt).status_code == 403                 # noc_n1 reads, does not ask
    assert _ask(client, hdr(client, "carol", seed, "A"), olt).status_code == 403                # an auditor neither
    assert _ask(client, hdr(client, "bob", seed, "B"), olt).status_code == 404                  # another provider's OLT does not exist for them
    assert _ask(client, h, str(uuid4())).status_code == 404
    with migrated.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query'")).scalar_one() == 0
    cat = {i["id"]: i for i in client.get(f"/v1/olts/{olt}/queries", headers=h).json()["items"]}
    assert cat["olt.version"]["offered"] and cat["olt.board"]["offered"] and cat["pon.ont.info"]["reason"] == "query_not_enabled"
    d = {i["id"]: i for i in client.get(f"/v1/olts/{olt}/queries", headers=hdr(client, "dave", seed, "A")).json()["items"]}
    assert d["olt.version"]["reason"] == "not_permitted"


def test_idempotency_and_audit(client, seed, inv, olt, on, migrated):
    h = hdr(client, "alice", seed, "A")
    k = _key()
    a, b = _ask(client, h, olt, "olt.version", key=k), _ask(client, h, olt, "olt.version", key=k)
    assert a.json()["outcome"] == "submitted" and b.json()["outcome"] == "existing" and a.json()["job"]["id"] == b.json()["job"]["id"]
    assert _ask(client, h, olt, "olt.board", key=k).status_code == 409        # same key, different intent
    with migrated.connect() as c:
        ev = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE action = 'job.preview' AND target_id = :j"), {"j": a.json()["job"]["id"]}).scalar_one()
    assert ev["olt_query"]["query_id"] == "olt.version" and ev["olt_query"]["olt_ref"] == olt


def test_quota_per_user_and_per_tenant(client, seed, inv, olt, on, monkeypatch):
    h = hdr(client, "alice", seed, "A")
    monkeypatch.setattr(olt_query, "USER_PER_HOUR", 3)
    assert [_ask(client, h, olt).status_code for _ in range(3)] == [200, 200, 200]
    r = _ask(client, h, olt)
    assert (r.status_code, r.json()["detail"]) == (429, "olt_query_quota")
    key = _key()
    monkeypatch.setattr(olt_query, "USER_PER_HOUR", 10)
    monkeypatch.setattr(olt_query, "TENANT_PER_HOUR", 3)
    assert _ask(client, h, olt).status_code == 429                              # the tenant is at its limit even though the user is not
    monkeypatch.setattr(olt_query, "TENANT_PER_HOUR", 60)
    assert _ask(client, h, olt, key=key).status_code == 200


def test_without_the_channel_an_approved_query_is_never_dispatched(client, seed, inv, olt, on, monkeypatch):
    h = hdr(client, "alice", seed, "A")
    assert _ask(client, h, olt).status_code == 200
    monkeypatch.setattr(olt_query, "EDGE_SUPPORT", False)
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204


def test_a_failed_submit_leaves_no_job_behind(client, seed, inv, olt, on, migrated, monkeypatch):
    from fastapi import HTTPException

    from app.api import jobs as jobs_mod

    def boom(*a, **k):
        raise HTTPException(409, "boom")
    h = hdr(client, "alice", seed, "A")
    k = _key()
    with monkeypatch.context() as m:
        m.setattr(jobs_mod, "submit", boom)
        assert _ask(client, h, olt, key=k).status_code == 409
    with migrated.connect() as c:    # preview and submit are one transaction: the preview did not survive the refusal, so a retry starts clean
        assert c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query'")).scalar_one() == 0
    assert _ask(client, h, olt, key=k).json()["outcome"] == "submitted"


def test_the_gates_are_asked_again_at_dispatch(client, seed, inv, olt, on, migrated):
    h = hdr(client, "alice", seed, "A")
    a = agent(client, inv, "a1")
    # the flag is turned off after the query was approved: it is cancelled, never sent
    jid = _ask(client, h, olt).json()["job"]["id"]
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE feature = 'olt_query'"))
    assert client.get("/v1/edge/jobs/next", headers=a).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "CANCELLED"
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE tenant_features SET enabled = true WHERE feature = 'olt_query'"))
    # the stored intent no longer matches what was hashed (someone with database access edited it): never sent either
    jid = _ask(client, h, olt).json()["job"]["id"]
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET params = jsonb_set(params, '{query_id}', '\"olt.version\"') WHERE id = :j AND params->>'query_id' = 'olt.board'"), {"j": jid})
        c.execute(text("UPDATE jobs SET params = jsonb_set(params, '{slot}', '1') WHERE id = :j"), {"j": jid})
    assert client.get("/v1/edge/jobs/next", headers=a).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "CANCELLED"


def test_quota_per_olt(client, seed, inv, olt, on, monkeypatch):
    h = hdr(client, "alice", seed, "A")
    monkeypatch.setattr(olt_query, "OLT_PER_HOUR", 2)
    assert [_ask(client, h, olt).status_code for _ in range(2)] == [200, 200]
    assert _ask(client, h, olt).status_code == 429


def test_the_path_decides_the_query_and_a_changed_intent_cannot_be_submitted(client, seed, inv, olt, on, migrated):
    h = hdr(client, "alice", seed, "A")
    r = client.post(f"/v1/olts/{olt}/queries/olt.version", headers={**h, **_key()}, json={"params": {"query_id": "olt.board"}})
    assert r.status_code == 422
    # a PREVIEWED job whose stored params were edited after the hash: submit refuses it
    from app.api import jobs as jobs_mod
    pv = client.post("/v1/jobs/preview", headers={**h, **_key()},
                     json={"operation": "olt_query", "target_id": olt, "params": {"query_id": "olt.version"}}).json()
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET params = jsonb_set(params, '{query_id}', '\"olt.board\"') WHERE id = :j"), {"j": pv["id"]})
    r = client.post(f"/v1/jobs/{pv['id']}/submit", headers=h)
    assert (r.status_code, r.json()["detail"]) == (409, "intent_changed")
    assert jobs_mod.OPERATIONS["olt_query"].writes is False
    assert client.get(f"/v1/jobs/{pv['id']}", headers=h).json()["status"] == "PREVIEWED"
