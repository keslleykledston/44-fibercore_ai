"""`olt_query` (ADR-0029), cloud half: the closed intent, the gates (flag, Edge channel, rollout, permission, quota) and what the signed envelope carries.
Nothing here reaches equipment. The tenant flag decides whether anything is offered; a test that needs the channel switched off sets `EDGE_SUPPORT` False itself."""
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


def test_nothing_is_offered_nor_created_while_the_tenant_flag_is_off(client, seed, inv, olt, migrated):
    h = hdr(client, "alice", seed, "A")
    cat = client.get(f"/v1/olts/{olt}/queries", headers=h).json()
    assert cat["enabled"] is False and not any(i["offered"] for i in cat["items"]) and cat["catalog_version"] == olt_query.catalog_version()
    r = _ask(client, h, olt)
    assert (r.status_code, r.json()["detail"]) == (409, "olt_query_disabled")
    r = client.post("/v1/jobs/preview", headers={**h, **_key()}, json={"operation": "olt_query", "target_id": olt, "params": {"query_id": "olt.version"}})
    assert (r.status_code, r.json()["detail"]) == (409, "olt_query_disabled")   # the generic route cannot get around it
    with migrated.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query'")).scalar_one() == 0


def test_the_flag_alone_is_not_enough_when_the_channel_is_switched_off_in_code_and_the_cli_refuses_it(client, seed, inv, olt, migrated, monkeypatch):
    monkeypatch.setattr(olt_query, "EDGE_SUPPORT", False)
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
    monkeypatch.setenv("ADMIN_DATABASE_URL", str(migrated.url.render_as_string(hide_password=False)))
    with pytest.raises(SystemExit, match="cannot be turned on"):
        cli.main(["feature-set", str(seed["A"]), "olt_query", "on"])


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


def test_the_vectors_the_edge_pins_are_the_ones_the_cloud_computes():
    """agents/edge pins the same two values (olt.pinnedCatalogVersion, jobs.qHash): if either side changes, one of the two test suites fails."""
    from app.api.jobs import _intent_hash
    from uuid import UUID
    oid = UUID("8f14e45f-ceea-467a-9a36-4a1b5c3d2e10")
    assert olt_query.catalog_version() == "1e1e5b3010c3788d6d86ae858c3d7bc976fc40a56916342d131b42acd5723b84"
    params = olt_query.build_intent(oid, {"query_id": "pon.ont.info", "slot": 1, "port": 0})
    assert _intent_hash("olt_query", "olt", oid, params) == "775f8c74e86cbbd5112a6c798605ab0654c31a748b05fae20024e74e3393adde"


def _report(client, inv, jid, **body):
    return client.post(f"/v1/edge/jobs/{jid}/result", headers=agent(client, inv, "a1"), json=body)


def _dispatched(client, seed, inv, olt, qid="olt.version"):
    h = hdr(client, "alice", seed, "A")
    jid = _ask(client, h, olt, qid).json()["job"]["id"]
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 200
    return h, jid


VERSION = {"product": "MA5608T", "version": "MA5600V800R015C00", "patch": "SPC100 HP1013", "uptime_seconds": 88838745}
BOARD = {"boards": [{"slot": 0, "name": "H805GPFD", "status": "Normal"}, {"slot": 2, "name": "H801MCUD1", "status": "Active_normal"}], "empty_slots": [3]}


def test_the_typed_result_is_stored_in_its_exact_shape(client, seed, inv, olt, on):
    h, jid = _dispatched(client, seed, inv, olt)
    assert _report(client, inv, jid, state="accepted").status_code == 204
    assert _report(client, inv, jid, state="succeeded", postcheck_ok=True, data=VERSION).status_code == 204
    j = client.get(f"/v1/jobs/{jid}", headers=h).json()
    assert j["status"] == "SUCCEEDED" and j["result"]["data"] == VERSION
    assert _report(client, inv, jid, state="succeeded", postcheck_ok=True, data=VERSION).status_code == 204     # the Edge's resend is a no-op
    h, jid = _dispatched(client, seed, inv, olt, "olt.board")
    assert _report(client, inv, jid, state="succeeded", postcheck_ok=True, data=BOARD).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["result"]["data"] == BOARD


def test_a_result_that_is_not_the_closed_shape_is_a_failure_and_is_not_stored(client, seed, inv, olt, on):
    bad = [None, {}, {**VERSION, "extra": "x"}, {**VERSION, "product": "<script>"}, {**VERSION, "uptime_seconds": "5"}, {**VERSION, "uptime_seconds": True},
           {"raw": "display version\n  VERSION : x"}, BOARD]   # the board shape for a version query
    for data in bad:
        h, jid = _dispatched(client, seed, inv, olt)
        assert _report(client, inv, jid, state="succeeded", postcheck_ok=True, **({"data": data} if data is not None else {})).status_code == 204
        j = client.get(f"/v1/jobs/{jid}", headers=h).json()
        assert j["status"] == "FAILED" and "data" not in j["result"] and j["result"]["detail"] == "invalid_result", (data, j)


def test_board_shape_is_checked_too_and_data_does_not_ride_on_other_outcomes(client, seed, inv, olt, on):
    for data in ({"boards": [], "empty_slots": []}, {"boards": [{"slot": 99, "name": "H805GPFD", "status": "Normal"}], "empty_slots": []},
                 {"boards": [{"slot": 0, "name": "H805GPFD", "status": "Normal"}], "empty_slots": [0]},
                 {"boards": [{"slot": 0, "name": "H805GPFD", "status": "Normal", "x": 1}], "empty_slots": []}, VERSION):
        h, jid = _dispatched(client, seed, inv, olt, "olt.board")
        _report(client, inv, jid, state="succeeded", postcheck_ok=True, data=data)
        assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "FAILED", data
    h, jid = _dispatched(client, seed, inv, olt)
    assert _report(client, inv, jid, state="failed", detail="device_rejected", data=VERSION).status_code == 422
    assert _report(client, inv, jid, state="succeeded", postcheck_ok=False, data=VERSION).status_code == 422
    assert _report(client, inv, jid, state="succeeded", postcheck_ok=False).status_code == 204     # unknown outcome after a restart
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "UNKNOWN"


# ---- ownership: the lease, the epoch and the two-phase transfer (ADR-0029 item 3)
def _lease(resp):
    import base64
    import json
    raw = resp.headers.get("X-OLT-Lease")
    return json.loads(base64.b64decode(raw)) if raw else None


def _cli(monkeypatch, migrated, *argv):
    from app import cli
    monkeypatch.setenv("ADMIN_DATABASE_URL", str(migrated.url.render_as_string(hide_password=False)))
    cli.main(list(argv))


def test_the_lease_names_the_olts_this_edge_owns_with_their_epoch(client, seed, inv, olt, on):
    from app.core import jobsign
    r = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    lease = _lease(r)
    assert lease and lease["schema"] == "olt-lease/1" and jobsign.verify(_pub_b64(), lease)
    assert {"target_ref": olt, "owner_epoch": 1} in lease["targets"]
    assert lease["edge_id"] == str(inv["a1"]["edge"]) and lease["tenant_id"] == str(seed["A"])
    other = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a2"))
    assert not _lease(other) or all(t["target_ref"] != olt for t in _lease(other)["targets"])      # another Edge is not leased this OLT
    assert "X-Bench-Lease" not in r.headers or _lease(r)["schema"] != "bench-lease/1"


def test_no_lease_without_the_flag_or_the_channel(client, seed, inv, olt, migrated, monkeypatch):
    assert _lease(client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))) is None      # the flag is off
    monkeypatch.setattr(olt_query, "EDGE_SUPPORT", False)
    assert _lease(client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))) is None      # the channel is switched off in code


def test_the_envelope_carries_the_owner_epoch(client, seed, inv, olt, on, migrated):
    h = hdr(client, "alice", seed, "A")
    _ask(client, h, olt)
    e = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).json()
    assert e["owner_epoch"] == 1
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET owner_epoch = 4 WHERE id = :o"), {"o": olt})
    _ask(client, h, olt, "olt.board")
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).json()["owner_epoch"] == 4
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET owner_epoch = 1 WHERE id = :o"), {"o": olt})


def test_a_transfer_in_two_phases(client, seed, inv, olt, on, migrated, monkeypatch):
    h = hdr(client, "alice", seed, "A")
    a1, a2 = agent(client, inv, "a1"), agent(client, inv, "a2")
    jid = _ask(client, h, olt).json()["job"]["id"]                                       # approved, not yet dispatched
    t, o, new = str(seed["A"]), olt, str(inv["a2"]["edge"])
    _cli(monkeypatch, migrated, "olt-transfer-start", t, o, new)
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "CANCELLED"       # open queries end with the transfer
    assert client.get("/v1/edge/jobs/next", headers=a1).status_code == 204
    assert not _lease(client.get("/v1/edge/jobs/next", headers=a1)) or all(x["target_ref"] != olt for x in _lease(client.get("/v1/edge/jobs/next", headers=a1))["targets"])
    assert _ask(client, h, olt).status_code == 200 and client.get("/v1/edge/jobs/next", headers=a1).status_code == 204   # accepted, never dispatched mid-transfer
    assert _ask(client, h, olt, "olt.board").status_code == 200
    with pytest.raises(SystemExit):                                                       # the same OLT cannot be moved twice at once
        _cli(monkeypatch, migrated, "olt-transfer-start", t, o, new)
    # phase 2 waits for the old owner's last lease
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET lease_until = now() + interval '30 seconds' WHERE id = :o"), {"o": o})
    with pytest.raises(SystemExit, match="may still hold a lease"):
        _cli(monkeypatch, migrated, "olt-transfer-finish", t, o)
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET lease_until = now() - interval '2 minutes' WHERE id = :o"), {"o": o})
        c.execute(text("UPDATE jobs SET status = 'CANCELLED' WHERE operation = 'olt_query' AND status = 'APPROVED'"))
    _cli(monkeypatch, migrated, "olt-transfer-finish", t, o)
    lease = _lease(client.get("/v1/edge/jobs/next", headers=a2))
    assert {"target_ref": olt, "owner_epoch": 2} in lease["targets"]                       # the new owner, one generation up
    old = _lease(client.get("/v1/edge/jobs/next", headers=a1))
    assert not old or all(x["target_ref"] != olt for x in old["targets"])
    with migrated.connect() as c:
        assert c.execute(text("SELECT edge_id::text, owner_epoch, transfer_to FROM olts WHERE id = :o"), {"o": o}).one() == (new, 2, None)
    with pytest.raises(SystemExit):
        _cli(monkeypatch, migrated, "olt-transfer-finish", t, o)                           # nothing left to finish


def test_the_application_role_cannot_move_an_olt(client, seed, inv, olt, migrated):
    from sqlalchemy.exc import DBAPIError
    for stmt in ("UPDATE olts SET owner_epoch = 9", "UPDATE olts SET edge_id = edge_id", "UPDATE olts SET transfer_to = edge_id, transfer_started_at = now()"):
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text("SET LOCAL ROLE fibercore_app"))
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(stmt))


def test_the_recorded_lease_end_is_the_signed_one_and_a_racing_transfer_takes_the_olt_out(client, seed, inv, olt, on, migrated, monkeypatch):
    from datetime import datetime

    from app.core import olt_ownership
    lease = _lease(client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")))
    signed_end = datetime.fromisoformat(lease["expires_at"])
    with migrated.connect() as c:
        recorded = c.execute(text("SELECT lease_until FROM olts WHERE id = :o"), {"o": olt}).scalar_one()
    assert recorded >= signed_end                       # never earlier than what the Edge can honour
    assert signed_end.microsecond == 0 and datetime.fromisoformat(lease["issued_at"]).microsecond == 0
    # the transfer started between listing the eligible OLTs and recording the lease: the OLT is NOT in the lease that goes out
    real = olt_ownership.lease_targets
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET transfer_to = :e, transfer_started_at = now() WHERE id = :o"), {"e": inv["a2"]["edge"], "o": olt})
    monkeypatch.setattr(olt_ownership, "lease_targets", lambda *a: [{"target_ref": olt, "owner_epoch": 1}])
    r = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    assert _lease(r) is None
    monkeypatch.setattr(olt_ownership, "lease_targets", real)
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET transfer_to = NULL, transfer_started_at = NULL WHERE id = :o"), {"o": olt})


def test_snapshots_follow_the_owner_after_a_transfer(client, seed, inv, olt, on, migrated, monkeypatch):
    name = next(o["name"] for o in client.get("/v1/olts", headers=hdr(client, "alice", seed, "A")).json() if o["id"] == olt)
    _cli(monkeypatch, migrated, "olt-transfer-start", str(seed["A"]), olt, str(inv["a2"]["edge"]))
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv, name=name)).status_code == 202   # the owner keeps reporting meanwhile
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a2"), json=snap(inv, key="a2", name=name)).status_code == 409
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET lease_until = now() - interval '2 minutes' WHERE id = :o"), {"o": olt})
    _cli(monkeypatch, migrated, "olt-transfer-finish", str(seed["A"]), olt)
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a2"), json=snap(inv, key="a2", name=name)).status_code == 202
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv, name=name)).status_code == 409   # the old owner is told


def test_a_query_lives_long_enough_for_the_worst_collection_wait(client, seed, inv, olt, on, migrated):
    from datetime import datetime, timedelta
    h = hdr(client, "alice", seed, "A")
    j = _ask(client, h, olt).json()["job"]
    life = datetime.fromisoformat(j["expires_at"]) - datetime.now(j and datetime.fromisoformat(j["expires_at"]).tzinfo)
    assert timedelta(minutes=21) < life <= timedelta(minutes=22)                 # a request right after a window: 15 min interval + the ~3 min collection, with margin
    e = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).json()
    assert datetime.fromisoformat(e["expires_at"]) - datetime.fromisoformat(e["issued_at"]) <= timedelta(minutes=20)   # what the Edge accepts
    other = client.post("/v1/jobs/preview", headers={**h, **_key()}, json={"operation": "collect", "target_id": olt, "params": {}}).json()["id"]
    j2 = client.post(f"/v1/jobs/{other}/submit", headers=h).json()
    assert datetime.fromisoformat(j2["expires_at"]) - datetime.now(datetime.fromisoformat(j2["expires_at"]).tzinfo) <= timedelta(minutes=15)   # other operations keep 15 min
    assert client.post(f"/v1/jobs/{other}/cancel", headers=h).status_code == 200     # leave nothing behind for the other modules
