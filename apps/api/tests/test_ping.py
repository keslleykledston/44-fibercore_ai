"""Ping test TR-143 IPPing, cloud half (ADR-0030 amendment line Q1, ADR-0039): the arithmetic, the closed shape of what an Edge reports, the request path through
the existing job engine and the bench gate (nothing opens by itself), the reservation shared with the speed test, tenant isolation and the owner CLI. The Edge
is a fake: it only answers `/v1/edge/jobs/next` and `/v1/edge/jobs/{id}/result`, as the real one does."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import bench, probe, speed
from tests.conftest import agent, hdr
from tests.test_jobs import idem
from tests.test_jobs_bench import _approver, _bench, _cpe, _flag
from tests.test_jobs_bench import _cleanup as _bench_cleanup  # noqa: F401  (autouse: bench lists, authorizations, registry, CPEs)
from tests.test_speed import _endpoint as _speed_endpoint
from tests.test_speed import _link

TG = "core-ping-1"
PARAMS = {"target": TG}


@pytest.fixture(autouse=True)
def _ping_cleanup(migrated, monkeypatch):
    monkeypatch.setattr(bench, "EDGE_SUPPORT", True)
    monkeypatch.setattr(bench, "SPEED_EDGE_SUPPORT", True)
    monkeypatch.setattr(bench, "PING_EDGE_SUPPORT", True)
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM ping_test_runs"))
        c.execute(text("DELETE FROM speed_test_runs"))
        c.execute(text("DELETE FROM job_approvals WHERE job_id IN (SELECT id FROM jobs WHERE operation IN ('ping_test') OR operation LIKE 'speed_test_%')"))
        c.execute(text("DELETE FROM jobs WHERE operation IN ('ping_test') OR operation LIKE 'speed_test_%'"))
        c.execute(text("DELETE FROM probe_targets"))
        c.execute(text("DELETE FROM speed_endpoints"))
        c.execute(text("DELETE FROM audit_log WHERE action LIKE 'ping.%' OR action LIKE 'speed.%'"))
        c.execute(text("DELETE FROM onu_cpe_links WHERE onu_id IN (SELECT id FROM onus WHERE olt_id IN (SELECT id FROM olts WHERE name = 'OLT-SPD'))"))
        c.execute(text("DELETE FROM olts WHERE name = 'OLT-SPD'"))


# ---- the arithmetic -------------------------------------------------------------------------------------------------------------------------------
def report(state="Completed", **kw):
    base = {"target": TG, "state": state, "success": 5, "failure": 0, "avg_ms": 12, "min_ms": 10, "max_ms": 15, "polling_ms": 3100}
    return {**base, **kw}


def comp(**kw):
    return probe.compute(probe.check_report(TG, report(**kw)))


def test_a_clean_run_has_no_loss_and_the_spread_is_max_minus_min_not_jitter():
    c = comp()
    assert (c.outcome, c.success, c.failure, c.loss_pct, c.avg_ms, c.min_ms, c.max_ms, c.reason) == ("completed", 5, 0, 0.0, 12, 10, 15, None)
    assert c.spread_ms == 5


@pytest.mark.parametrize("ok,loss", [(4, 20.0), (3, 40.0), (2, 60.0), (1, 80.0)])
def test_loss_is_computed_from_the_counts(ok, loss):
    c = comp(success=ok, failure=5 - ok)
    assert (c.outcome, c.loss_pct) == ("completed", loss) and c.avg_ms == 12


def test_every_probe_lost_is_a_completed_result_with_full_loss_and_no_times_never_a_zero():
    c = comp(success=0, failure=5, avg_ms=0, min_ms=0, max_ms=0)    # the CPE still shows the leftover of an earlier test: not kept
    assert (c.outcome, c.success, c.failure, c.loss_pct) == ("completed", 0, 5, 100.0)
    assert (c.avg_ms, c.min_ms, c.max_ms, c.spread_ms) == (None, None, None, None)


@pytest.mark.parametrize("kw,reason", [
    ({"success": None}, "no_counts"), ({"failure": None}, "no_counts"),
    ({"success": 4, "failure": 2}, "counts_mismatch"), ({"success": 1, "failure": 1}, "counts_mismatch"), ({"success": 5, "failure": 5}, "counts_mismatch"),
    ({"avg_ms": None}, "no_times"), ({"min_ms": None}, "no_times"), ({"max_ms": None}, "no_times"),
    ({"min_ms": 20}, "times_inconsistent"), ({"avg_ms": 99}, "times_inconsistent"),
])
def test_counts_and_times_that_do_not_add_up_give_no_figure_at_all(kw, reason):
    c = comp(**kw)
    assert (c.outcome, c.reason) == ("inconclusive", reason)
    assert (c.success, c.failure, c.loss_pct, c.avg_ms, c.min_ms, c.max_ms) == (None,) * 6     # never 0, never a guess


@pytest.mark.parametrize("state,reason", [("Error_CannotResolveHostName", "device_error"), ("Error_Other", "device_error"), ("Requested", "not_completed"), ("None", "not_completed")])
def test_a_device_that_did_not_complete_yields_an_error_and_no_figure(state, reason):
    c = comp(state=state)
    assert (c.outcome, c.reason, c.success, c.avg_ms, c.loss_pct) == ("error", reason, None, None, None)


def test_every_computed_result_fits_the_table_it_is_stored_in():
    """store_result must never be refused by a CHECK (the Edge would re-send a report that can never be accepted): sweep the inputs the shape allows."""
    for s in (None, 0, 1, 4, 5, 6):
        for f in (None, 0, 1, 4, 5):
            for avg, lo, hi in ((None, None, None), (0, 0, 0), (12, 10, 15), (10, 10, 10), (15, 10, 12), (None, 3, 4)):
                for st in ("Completed", "Error_X", "Requested"):
                    c = probe.compute(probe.check_report(TG, report(state=st, success=s, failure=f, avg_ms=avg, min_ms=lo, max_ms=hi)))
                    assert (c.success is None) == (c.loss_pct is None) == (c.failure is None), c
                    assert c.success is None or c.outcome == "completed", c
                    assert (c.avg_ms is None) == (c.min_ms is None) == (c.max_ms is None), c
                    assert c.avg_ms is None or (c.success > 0 and c.min_ms <= c.avg_ms <= c.max_ms), c
                    assert c.loss_pct is None or 0 <= c.loss_pct <= 100, c


@pytest.mark.parametrize("mut", [
    lambda d: {**d, "host": "10.0.0.1"},                          # a field the shape does not know
    lambda d: {**d, "target": "other-node"},                      # a report for another destination
    lambda d: {**d, "state": "Completed; DROP"},                  # free text in the state
    lambda d: {**d, "success": -1},
    lambda d: {**d, "success": True},                             # a boolean is not a count
    lambda d: {**d, "avg_ms": 10**9},
    lambda d: {**d, "avg_ms": 1.5},
    lambda d: {**d, "polling_ms": 600_001},
    lambda d: {k: v for k, v in d.items() if k != "state"},
    lambda d: {k: v for k, v in d.items() if k != "target"},
    lambda d: "Completed",
    lambda d: None,
])
def test_the_edge_report_is_accepted_only_in_its_exact_shape(mut):
    assert probe.check_report(TG, mut(report())) is None


def test_a_leaf_the_device_did_not_give_is_absent_not_zero():
    d = report()
    del d["avg_ms"], d["min_ms"], d["max_ms"]
    assert probe.check_report(TG, d)["avg_ms"] is None


def test_catalog_parameter_is_one_logical_name_and_nothing_else():
    assert bench.params_valid("ping_test", PARAMS)
    for bad in ({}, {"target": TG, "profile": "10mb"}, {"host": "10.0.0.1"}, {"target": "http://10.0.0.1/f"}, {"target": "10.0.0.1"}, {"target": "Core1"}, {"target": 3}):
        assert not bench.params_valid("ping_test", bad), bad


# ---- setup helpers --------------------------------------------------------------------------------------------------------------------------------
def _ping_flag(migrated, tenant, on=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'quality_active_tests',:e)"), {"t": tenant, "e": on})


def _target(migrated, seed, inv, tid=TG, kind="CORE", enabled=True, edge="a1"):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO probe_targets (tenant_id, id, label, target_kind, region, enabled, edge_id) VALUES (:t,:i,'Destino do core',:k,'DC-1',:e,:g)"),
                  {"t": seed["A"], "i": tid, "k": kind, "e": enabled, "g": inv[edge]["edge"]})


def _ready(client, seed, inv, migrated, serial="BNCH-CPE-0001", ext="bench-ext-0001", first=True, link=True, **kw):
    """Everything open for one bench CPE: flags, destination, PON link, registry evidence, the owner's prior authorization."""
    if first:
        _flag(migrated, seed["A"])
        _ping_flag(migrated, seed["A"])
        _target(migrated, seed, inv)
    cpe = _cpe(client, inv, seed, serial=serial, ext=ext)
    _bench(migrated, seed, inv, cpe, op="ping_test", params=PARAMS, capability=first, **kw)
    if link:
        _link(migrated, seed, inv, cpe)
    return cpe


def _post(client, h, cpe, **kw):
    body = {"target_id": TG, **kw}
    key = body.pop("key", None)
    return client.post(f"/v1/cpes/{cpe}/ping/runs", headers={**h, "Idempotency-Key": key or uuid4().hex}, json=body)


def _rows(migrated, sql, **a):
    with migrated.begin() as c:
        return c.execute(text(sql), a).all()


def _dispatched(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    h = hdr(client, "alice", seed, "A")
    run = _post(client, h, cpe).json()["run"]
    assert client.post(f"/v1/jobs/{run['job_id']}/approve", headers=_approver(client, seed, migrated)).json()["status"] == "APPROVED"
    env = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    assert env.status_code == 200
    return cpe, h, run, env.json()


def _send(client, inv, run, **body):
    return client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"), json=body)


def _ok(client, inv, run, data=None):
    return _send(client, inv, run, state="succeeded", postcheck_ok=True, data=data if data is not None else report())


# ---- flag, permission, tenant ---------------------------------------------------------------------------------------------------------------------
def test_everything_answers_feature_disabled_while_the_flag_is_off_and_creates_nothing(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    h = hdr(client, "alice", seed, "A")
    for r in (client.get(f"/v1/cpes/{cpe}/ping/capabilities", headers=h), client.get(f"/v1/cpes/{cpe}/ping/runs", headers=h), _post(client, h, cpe)):
        assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
    assert _rows(migrated, "SELECT 1 FROM jobs WHERE operation = 'ping_test'") == [] and _rows(migrated, "SELECT 1 FROM ping_test_runs") == []


def test_only_the_roles_that_carry_the_permission_can_ask(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    for who in ("dave", "carol"):
        assert _post(client, hdr(client, who, seed, "A"), cpe).status_code == 403, who
    assert _rows(migrated, "SELECT 1 FROM ping_test_runs") == []


def test_the_flag_defaults_off_and_the_permission_is_in_the_catalog():
    from app.core import features
    from app.core.permissions import CATALOG
    assert features.FEATURES["quality_active_tests"] is False
    assert "diagnostics:ping_run" in CATALOG


# ---- capabilities screen --------------------------------------------------------------------------------------------------------------------------
def test_a_cpe_outside_the_bench_list_is_never_offered_and_says_why(client, seed, inv, migrated):
    _ping_flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    j = client.get(f"/v1/cpes/{cpe}/ping/capabilities", headers=hdr(client, "alice", seed, "A")).json()
    assert j["bench_target"] is False and j["ready"] is False and j["test"]["reason"] == "operation_not_homologated"


def test_the_screen_is_ready_only_with_a_bench_target_registry_evidence_and_a_destination_of_its_edge(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    j = client.get(f"/v1/cpes/{cpe}/ping/capabilities", headers=hdr(client, "alice", seed, "A")).json()
    assert j["test"]["offered"] is True and j["ready"] is True and j["targets"][0]["id"] == TG and j["targets"][0]["ready"] is True
    assert j["shape"] == {"repetitions": 5, "timeout_ms": 1000} and j["limits"] == {"per_cpe_live": 1, "per_cpe_per_hour": 6}
    assert j["unsupported"] == ["dns_test", "jitter"]
    blob = str(j).lower()
    assert "http" not in blob and "10." not in blob      # a logical id, never an address


def test_without_registry_evidence_the_test_is_not_offered(client, seed, inv, migrated):
    _flag(migrated, seed["A"]); _ping_flag(migrated, seed["A"]); _target(migrated, seed, inv)
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, op="ping_test", params=PARAMS, capability=False)
    _link(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    assert client.get(f"/v1/cpes/{cpe}/ping/capabilities", headers=h).json()["test"]["reason"] == "capability_not_observed"
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "capability_not_observed"


def test_a_destination_owned_by_another_edge_or_disabled_is_not_ready(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    h = hdr(client, "alice", seed, "A")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        other = c.execute(text("INSERT INTO edges (tenant_id, name) VALUES (:t, 'edge-2') RETURNING id"), {"t": seed["A"]}).scalar()
        c.execute(text("UPDATE probe_targets SET edge_id = :e"), {"e": other})
    assert client.get(f"/v1/cpes/{cpe}/ping/capabilities", headers=h).json()["ready"] is False
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "target_unavailable"
    with migrated.begin() as c:
        c.execute(text("UPDATE probe_targets SET edge_id = :e, enabled = false"), {"e": inv["a1"]["edge"]})
    assert _post(client, h, cpe).json()["reason"] == "target_unavailable"
    with migrated.begin() as c:
        c.execute(text("DELETE FROM edges WHERE id = :e"), {"e": other})


def test_the_generic_jobs_api_never_creates_a_ping_job(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    r = client.post("/v1/jobs/preview", headers={**hdr(client, "alice", seed, "A"), **idem()}, json={"operation": "ping_test", "target_id": cpe, "params": PARAMS})
    assert r.status_code == 409 and r.json()["detail"] == "use_ping_api"
    assert _rows(migrated, "SELECT 1 FROM jobs WHERE operation = 'ping_test'") == []


def test_turning_the_flag_off_stops_a_request_made_before(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    with migrated.begin() as c:
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE feature = 'quality_active_tests'"))
    from app.api import jobs as jobs_mod
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert bench.gate(c, seed["A"], jobs_mod._load(c, run["job_id"]), mode="dispatch") == "ping_disabled"


def test_disabling_the_destination_stops_a_request_made_before(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    with migrated.begin() as c:
        c.execute(text("UPDATE probe_targets SET enabled = false"))
    from app.api import jobs as jobs_mod
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert bench.gate(c, seed["A"], jobs_mod._load(c, run["job_id"]), mode="dispatch") == "target_unavailable"


# ---- the request path -----------------------------------------------------------------------------------------------------------------------------
def test_blockers_are_answered_with_a_status_a_code_and_an_audit_row_and_leave_no_live_job(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated, link=False)
    h = hdr(client, "alice", seed, "A")
    assert _post(client, h, cpe, target_id="nope-1").json() == {"outcome": "blocked", "reason": "target_unavailable", "run": None}
    assert _rows(migrated, "SELECT 1 FROM jobs WHERE operation = 'ping_test'") == []
    why = {r.evidence_redacted["reason"] for r in _rows(migrated, "SELECT evidence_redacted FROM audit_log WHERE action = 'ping.blocked'")}
    assert why == {"target_unavailable"}


def test_a_request_needs_no_confirmed_onu_link_because_ping_has_no_pon_slot(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated, link=False)
    r = _post(client, hdr(client, "alice", seed, "A"), cpe)
    assert r.status_code == 201 and r.json()["outcome"] == "submitted"


def test_a_request_is_a_job_of_the_existing_engine_and_never_leaves_before_an_approval(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    h = hdr(client, "alice", seed, "A")
    r = _post(client, h, cpe)
    assert r.status_code == 201 and r.json()["outcome"] == "submitted" and r.json()["run"]["status"] == "awaiting_approval"
    run = r.json()["run"]
    assert run["target_id"] == TG and run["loss_pct"] is None and run["avg_ms"] is None      # no figure before a result
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204
    job = client.get(f"/v1/jobs/{run['job_id']}", headers=h).json()
    assert job["operation"] == "ping_test" and job["status"] == "PENDING_APPROVAL" and job["required_approvals"] == 1
    assert _rows(migrated, "SELECT state FROM bench_authorizations")[0].state == "open"
    assert [a.action for a in _rows(migrated, "SELECT action FROM audit_log WHERE action LIKE 'ping.%'")] == ["ping.requested"]


def test_the_same_key_returns_the_same_run_and_a_different_test_under_it_is_refused(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _target(migrated, seed, inv, tid="core-ping-2")
    h = hdr(client, "alice", seed, "A")
    k = uuid4().hex
    a, b = _post(client, h, cpe, key=k), _post(client, h, cpe, key=k)
    assert a.status_code == 201 and b.status_code == 200 and b.json()["outcome"] == "existing" and b.json()["run"]["id"] == a.json()["run"]["id"]
    assert _post(client, h, cpe, key=k, target_id="core-ping-2").status_code == 409
    assert len(_rows(migrated, "SELECT 1 FROM ping_test_runs")) == 1


def test_no_edge_support_means_the_bench_path_is_not_visible_at_all(client, seed, inv, migrated, monkeypatch):
    monkeypatch.setattr(bench, "PING_EDGE_SUPPORT", False)
    cpe = _ready(client, seed, inv, migrated)
    h = hdr(client, "alice", seed, "A")
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "operation_not_homologated"
    assert client.get(f"/v1/cpes/{cpe}/ping/capabilities", headers=h).json()["ready"] is False
    assert _rows(migrated, "SELECT 1 FROM ping_test_runs") == []
    assert client.post("/v1/bench/authorizations", headers=h, json={"operation": "ping_test", "cpe_id": cpe, "params": PARAMS, "minutes": 30}).status_code == 409


# ---- the full path with a fake Edge ---------------------------------------------------------------------------------------------------------------
def test_the_envelope_carries_one_logical_name_and_no_address(client, seed, inv, migrated):
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "job-envelope.schema.json").read_text())
    _, _, run, env = _dispatched(client, seed, inv, migrated)
    assert not list(Draft202012Validator(schema).iter_errors(env)), "the ping envelope must match contracts/job-envelope.schema.json"
    assert list(Draft202012Validator(schema).iter_errors({**env, "params": {"target": "http://10.0.0.1/f"}})), "the contract must refuse a URL as the target"
    assert env["operation"] == "ping_test" and env["params"] == PARAMS and env["authorization_id"]
    blob = str(env).lower()
    assert "http" not in blob and "url" not in blob and "host" not in blob


def test_a_valid_report_becomes_a_computed_run_the_screen_can_read(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert _ok(client, inv, run, report(success=4, failure=1)).status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=h).json()
    assert got["status"] == "completed" and (got["sent"], got["success"], got["failure"], got["loss_pct"]) == (5, 4, 1, 20.0)
    assert (got["avg_ms"], got["min_ms"], got["max_ms"], got["spread_ms"]) == (12, 10, 15, 5) and "jitter" not in str(got).lower()
    assert client.get(f"/v1/cpes/{cpe}/ping/runs", headers=h).json()["items"][0]["id"] == run["id"]
    stored = str(_rows(migrated, "SELECT result FROM jobs WHERE id = :j", j=run["job_id"])[0].result)
    assert "avg_ms" not in stored and "success" not in stored                    # the raw report is not kept on the job: only the computed figures on the run
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is False


def test_a_report_re_sent_after_a_lost_acknowledgement_changes_nothing(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert _ok(client, inv, run).status_code == 204
    assert _ok(client, inv, run, report(success=1, failure=4)).status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=h).json()
    assert got["success"] == 5 and got["loss_pct"] == 0.0


def test_full_loss_is_shown_as_loss_with_dashes_for_the_times(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert _ok(client, inv, run, report(success=0, failure=5, avg_ms=0, min_ms=0, max_ms=0)).status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=h).json()
    assert got["status"] == "completed" and got["loss_pct"] == 100.0 and (got["avg_ms"], got["min_ms"], got["max_ms"], got["spread_ms"]) == (None,) * 4
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is False


def test_a_device_error_is_a_clear_result_not_a_failed_write(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert _ok(client, inv, run, {"target": TG, "state": "Error_CannotResolveHostName"}).status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=h).json()
    assert got["status"] == "error" and got["reason"] == "device_error" and got["loss_pct"] is None and got["avg_ms"] is None
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is False


def test_the_most_extreme_accepted_report_is_acknowledged_and_stored_without_a_figure(client, seed, inv, migrated):
    """Counts that fit the leaf range but not the test must not be refused by a CHECK: the job commits and the run is inconclusive (the Edge is never left re-sending)."""
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert _ok(client, inv, run, report(success=probe.MAX_MS, failure=probe.MAX_MS, avg_ms=probe.MAX_MS, min_ms=0, max_ms=probe.MAX_MS)).status_code == 204
    assert _rows(migrated, "SELECT status FROM jobs WHERE id = :j", j=run["job_id"])[0].status == "SUCCEEDED"
    got = client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=h).json()
    assert got["status"] == "inconclusive" and got["reason"] == "counts_mismatch" and got["loss_pct"] is None


@pytest.mark.parametrize("data", [None, {}, {**report(), "extra": 1}, {**report(), "target": "other-node"}, {**report(), "state": "Done; rm -rf"}, {**report(), "success": True}])
def test_a_success_without_the_exact_report_of_this_job_is_a_failure_and_locks_the_target(client, seed, inv, migrated, data):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    body = {"state": "succeeded", "postcheck_ok": True, **({"data": data} if data is not None else {})}
    assert _send(client, inv, run, **body).status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=h).json()
    assert got["status"] == "error" and got["loss_pct"] is None and got["reason"] == "invalid_result"
    assert _rows(migrated, "SELECT status FROM jobs WHERE id = :j", j=run["job_id"])[0].status == "FAILED"
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is True


def test_an_uncertain_outcome_is_unknown_and_locks_the_target_and_data_rides_only_with_a_success(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert _send(client, inv, run, state="failed", data=report()).status_code == 422
    assert _send(client, inv, run, state="succeeded", postcheck_ok=False).status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=h).json()
    assert got["status"] == "error" and got["avg_ms"] is None                     # a run with no usable report is closed with an error and no figure
    assert _rows(migrated, "SELECT status FROM jobs WHERE id = :j", j=run["job_id"])[0].status == "UNKNOWN"
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is True


@pytest.mark.parametrize("detail,kept", [("wan_not_connected", "wan_not_connected"), ("ping_not_started", "ping_not_started"), ("timeout", "timeout"),
                                         ("no_response_from_10.1.2.3", "edge_error"), ("failed to reach 10.1.2.3:8080", "edge_error"), ("", "edge_error")])
def test_free_text_from_the_edge_never_reaches_the_stored_result_or_the_history(client, seed, inv, migrated, detail, kept):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert _send(client, inv, run, state="failed", detail=detail).status_code == 204
    stored = _rows(migrated, "SELECT result FROM jobs WHERE id = :j", j=run["job_id"])[0].result
    assert stored["detail"] == kept and "10.1.2.3" not in str(stored)
    got = client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=h).json()
    assert got["status"] == "error" and got["reason"] == kept and "10.1.2.3" not in str(got)


# ---- the reservation shared with the speed test, and the ceiling -----------------------------------------------------------------------------------
def test_one_diagnostic_at_a_time_per_cpe_and_the_slot_comes_back_when_the_job_ends(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "cpe_busy"
    assert _ok(client, inv, run).status_code == 204
    assert _post(client, h, cpe).json()["reason"] != "cpe_busy"        # the slot is free again (whatever the gate then says about the single-use authorization)


def test_a_live_ping_holds_the_cpe_against_a_speed_test_and_the_other_way_round(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    h = hdr(client, "alice", seed, "A")
    run = _post(client, h, cpe).json()["run"]
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        pon = speed.pon_of(c, seed["A"], cpe)
        assert speed.busy_reason(c, seed["A"], cpe, pon) == "cpe_busy"      # regression of the speed test: a live ping is a live diagnostic of this CPE
    # the other way round: a live speed run of this CPE blocks the ping
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET status = 'CANCELLED' WHERE id = :j"), {"j": run["job_id"]})
    _speed_endpoint(migrated, seed, inv)
    speed_job = _insert_live_speed_run(migrated, seed, inv, cpe)
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "cpe_busy", speed_job


def _insert_live_speed_run(migrated, seed, inv, cpe):
    t = str(seed["A"])
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t})
        job = c.execute(text("INSERT INTO jobs (tenant_id, operation, target_type, target_id, status, risk, requested_by, edge_id, idempotency_key, intent_hash, params, expires_at, required_approvals) "
                             "VALUES (:t,'speed_test_download','cpe',:c,'DISPATCHED','R2',:u,:e,:k,:h,CAST(:p AS jsonb), now() + interval '10 minutes', 1) RETURNING id"),
                        {"t": t, "c": cpe, "u": uuid4(), "e": inv["a1"]["edge"], "k": uuid4().hex, "h": "0" * 64, "p": '{"target":"core-sp-1","profile":"10mb"}'}).scalar()
        pon = speed.pon_of(c, seed["A"], cpe)
        c.execute(text("INSERT INTO speed_test_runs (tenant_id, cpe_id, job_id, group_id, direction, endpoint_id, profile, pon_id, requested_by) "
                       "VALUES (:t,:c,:j,gen_random_uuid(),'download','core-sp-1','10mb',:p,:u)"), {"t": t, "c": cpe, "j": job, "p": pon, "u": uuid4()})
    return job


def test_the_hourly_ceiling_per_cpe(client, seed, inv, migrated, monkeypatch):
    monkeypatch.setattr(probe, "MAX_RUNS_PER_HOUR", 1)
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert _ok(client, inv, run).status_code == 204
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "rate_limited"
    with migrated.begin() as c:   # an hour later the ceiling no longer counts it
        c.execute(text("UPDATE ping_test_runs SET created_at = now() - interval '61 minutes'"))
    assert _post(client, h, cpe).json()["reason"] != "rate_limited"


# ---- isolation and storage ------------------------------------------------------------------------------------------------------------------------
def test_runs_and_destinations_are_isolated_by_tenant_and_the_app_role_cannot_create_destinations(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    hb = hdr(client, "bob", seed, "B")
    assert client.get(f"/v1/cpes/{cpe}/ping/runs", headers=hb).status_code in (403, 404)
    assert client.get(f"/v1/cpes/{cpe}/ping/runs/{run['id']}", headers=hb).status_code in (403, 404)
    from app.core.db import get_engine
    with pytest.raises(DBAPIError):
        with get_engine().begin() as c:   # the application role: no INSERT on the catalog (only the owner CLI writes it)
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text("INSERT INTO probe_targets (tenant_id, id, label, target_kind, region, edge_id) VALUES (:t,'x-node-1','x','CORE','r',:e)"),
                      {"t": seed["A"], "e": inv["a1"]["edge"]})
    with pytest.raises(DBAPIError):
        with get_engine().begin() as c:   # nor re-bind or enable one
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text("UPDATE probe_targets SET enabled = false"))


@pytest.mark.parametrize("sql", [
    "INSERT INTO probe_targets (tenant_id, id, label, target_kind, region, edge_id) VALUES (:t,'Bad_Id','x','CORE','r',:e)",
    "INSERT INTO probe_targets (tenant_id, id, label, target_kind, region, edge_id) VALUES (:t,'ok-node','x','WAN','r',:e)",
    "INSERT INTO probe_targets (tenant_id, id, label, target_kind, region, edge_id) VALUES (:t,'http-10-0-0-1','x','CORE','http://10.0.0.1',:e)",
    "INSERT INTO probe_targets (tenant_id, id, label, target_kind, region) VALUES (:t,'no-edge','x','CORE','r')",
])
def test_the_destination_catalog_refuses_anything_that_is_not_a_logical_name_or_has_no_owner(migrated, seed, inv, sql):
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(sql), {"t": seed["A"], "e": inv["a1"]["edge"]})


def test_the_tables_have_no_column_that_could_hold_an_address(migrated):
    cols = {r.column_name for r in _rows(migrated, "SELECT column_name FROM information_schema.columns WHERE table_name IN ('probe_targets','ping_test_runs')")}
    assert not {c for c in cols if any(w in c for w in ("url", "host", "addr", "ip", "token", "secret", "password", "payload"))}, cols


@pytest.mark.parametrize("sql", [
    "UPDATE ping_test_runs SET outcome = 'error', completed_at = now(), success_count = 5, failure_count = 0, loss_pct = 0",       # a figure on an error
    "UPDATE ping_test_runs SET outcome = 'completed', completed_at = now(), success_count = 5",                                      # counts incomplete
    "UPDATE ping_test_runs SET outcome = 'completed', completed_at = now(), success_count = 0, failure_count = 5, loss_pct = 100, avg_ms = 0, min_ms = 0, max_ms = 0",   # times with no reply
    "UPDATE ping_test_runs SET outcome = 'completed', completed_at = now(), success_count = 5, failure_count = 0, loss_pct = 0, avg_ms = 9, min_ms = 10, max_ms = 15",  # avg below min
    "UPDATE ping_test_runs SET outcome = 'completed', completed_at = now(), success_count = 5, failure_count = 0, loss_pct = 0, avg_ms = 12",                      # avg without min/max
    "UPDATE ping_test_runs SET outcome = 'completed', completed_at = now(), success_count = 5, failure_count = 0, loss_pct = 101",
    "UPDATE ping_test_runs SET loss_pct = 0",                                                                                        # a figure with no outcome
])
def test_the_run_row_cannot_carry_a_figure_without_a_measurement(client, seed, inv, migrated, sql):
    _dispatched(client, seed, inv, migrated)
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text(sql))


def test_the_roles_that_may_authorize_a_bench_ping_match_the_sql_table():
    assert "ping_test" in bench.BENCH_AUTHORIZERS["engineer"] and "ping_test" in bench.BENCH_AUTHORIZERS["isp_admin"]
    assert "ping_test" not in bench.BENCH_AUTHORIZERS["noc_n2"]


# ---- owner CLI ------------------------------------------------------------------------------------------------------------------------------------
def test_owner_cli_manages_logical_destinations_and_ping_authorizations(client, seed, inv, migrated, admin_url, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t, edge = str(seed["A"]), str(inv["a1"]["edge"])
    for bad in ("http://10.0.0.1", "Core1", "a", "10.0.0.1/x"):
        with pytest.raises(SystemExit):
            cli.main(["probe-target-set", t, bad, "Destino", "CORE", "DC-1", "on", "--edge", edge])
    with pytest.raises(SystemExit, match="label"):
        cli.main(["probe-target-set", t, "core-ping-9", "http://10.0.0.1/f", "CORE", "DC-1", "on", "--edge", edge])
    with pytest.raises(SystemExit, match="unknown edge"):
        cli.main(["probe-target-set", t, "core-ping-9", "Destino do core", "CORE", "DC-1", "on", "--edge", str(inv["b1"]["edge"])])   # another provider's Edge
    cli.main(["probe-target-set", t, "core-ping-9", "Destino do core", "CORE", "DC-1", "on", "--edge", edge])
    cli.main(["probe-target-set", t, "core-ping-9", "Destino do core", "CORE", "DC-1", "off", "--edge", edge])
    assert _rows(migrated, "SELECT enabled FROM probe_targets WHERE id = 'core-ping-9'")[0].enabled is False
    cpe = _cpe(client, inv, seed)
    cli.main(["bench-target-add", t, cpe, edge])
    now = datetime.now(UTC)
    args = ["bench-authorize", t, "ping_test", cpe, "--from", (now - timedelta(minutes=1)).isoformat(), "--to", (now + timedelta(minutes=30)).isoformat(), "--by", "responsavel"]
    with pytest.raises(SystemExit, match="parameters outside"):
        cli.main(args)
    with pytest.raises(SystemExit, match="parameters outside"):
        cli.main([*args, "--ping-target", "http://10.0.0.1/f"])
    cli.main([*args, "--ping-target", TG])
    assert _rows(migrated, "SELECT params_hash FROM bench_authorizations WHERE operation = 'ping_test'")[0].params_hash.strip() == bench.params_hash(PARAMS)
    monkeypatch.setattr(bench, "PING_EDGE_SUPPORT", False)
    with pytest.raises(SystemExit, match="not delivered"):
        cli.main([*args, "--ping-target", TG])
