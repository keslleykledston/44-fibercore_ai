"""Speed Diagnostics TR-143, cloud half (ADR-0038): the arithmetic, the closed shape of what an Edge reports, the request path through the existing job
engine and the bench gate (nothing opens by itself), the limits that protect the PON, tenant isolation and the owner CLI. The Edge is a fake: it only
answers `/v1/edge/jobs/next` and `/v1/edge/jobs/{id}/result`, as the real one will."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import bench, speed
from tests.conftest import agent, hdr
from tests.test_jobs import idem
from tests.test_jobs_bench import PROFILE, _approver, _bench, _cpe, _flag
from tests.test_jobs_bench import _cleanup as _bench_cleanup  # noqa: F401  (autouse: bench lists, authorizations, registry, CPEs)

EP, PF = "core-sp-1", "10mb"
PARAMS = {"target": EP, "profile": PF}


@pytest.fixture(autouse=True)
def _speed_cleanup(migrated, monkeypatch):
    monkeypatch.setattr(bench, "EDGE_SUPPORT", True)
    monkeypatch.setattr(bench, "SPEED_EDGE_SUPPORT", True)   # the Edge half is PR 2; these tests exercise the cloud with a fake Edge
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM speed_test_runs"))
        c.execute(text("DELETE FROM job_approvals WHERE job_id IN (SELECT id FROM jobs WHERE operation LIKE 'speed_test_%')"))
        c.execute(text("DELETE FROM jobs WHERE operation LIKE 'speed_test_%'"))
        c.execute(text("DELETE FROM speed_endpoints"))
        c.execute(text("DELETE FROM audit_log WHERE action LIKE 'speed.%'"))
        c.execute(text("DELETE FROM onu_cpe_links WHERE onu_id IN (SELECT id FROM onus WHERE olt_id IN (SELECT id FROM olts WHERE name = 'OLT-SPD'))"))
        c.execute(text("DELETE FROM olts WHERE name = 'OLT-SPD'"))   # cascades its PONs and ONUs


# ---- the arithmetic -------------------------------------------------------------------------------------------------------------------------------
T0 = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)


def counters(direction="download", state="Completed", seconds=8.0, **kw):
    base = {"direction": direction, "target": EP, "profile": PF, "state": state, "bom": T0.isoformat(),
            "eom": (T0 + timedelta(seconds=seconds)).isoformat()}
    if direction == "download":
        base["test_bytes_received"] = 10_000_000
    else:
        base["test_file_length"] = 10_000_000
    return {**base, **kw}


def test_download_is_eight_times_the_received_bytes_over_the_device_interval():
    c = speed.compute("download", PF, speed.check_counters("download", EP, PF, counters(seconds=8.0)))
    assert (c.outcome, c.mbps, c.bytes, c.duration_ms, c.basis, c.reason) == ("completed", 10.0, 10_000_000, 8000, "test_bytes_received", None)


def test_upload_uses_the_bytes_the_device_sent_when_it_reports_them_else_the_requested_file_length():
    fl = speed.compute("upload", PF, speed.check_counters("upload", EP, PF, counters("upload", seconds=4.0)))
    assert (fl.mbps, fl.basis) == (20.0, "test_file_length")
    sent = speed.compute("upload", PF, speed.check_counters("upload", EP, PF, counters("upload", seconds=4.0, test_bytes_sent=9_900_000)))
    assert (sent.mbps, sent.basis) == (19.8, "test_bytes_sent")


def test_a_reported_zero_of_bytes_sent_is_not_a_missing_counter():
    c = speed.compute("upload", PF, speed.check_counters("upload", EP, PF, counters("upload", seconds=4.0, test_bytes_sent=0)))
    assert (c.outcome, c.mbps, c.reason, c.basis) == ("inconclusive", None, "no_bytes", "test_bytes_sent")
    absent = speed.compute("upload", PF, speed.check_counters("upload", EP, PF, counters("upload", seconds=4.0, test_bytes_sent=None)))
    assert (absent.outcome, absent.basis) == ("completed", "test_file_length")   # only a missing counter falls back to the requested length


def test_an_upload_counter_above_the_profile_is_also_inconclusive():
    c = speed.compute("upload", PF, speed.check_counters("upload", EP, PF, counters("upload", seconds=4.0, test_bytes_sent=50_000_000)))
    assert (c.outcome, c.mbps, c.reason, c.basis) == ("inconclusive", None, "bytes_exceed_profile", "test_bytes_sent")


def test_a_short_interval_or_a_short_transfer_is_partial_never_reliable():
    short_t = speed.compute("download", PF, speed.check_counters("download", EP, PF, counters(seconds=2.0)))
    assert (short_t.outcome, short_t.reason) == ("partial", "too_short") and short_t.mbps == 40.0
    short_b = speed.compute("download", PF, speed.check_counters("download", EP, PF, counters(seconds=6.0, test_bytes_received=5_000_000)))
    assert (short_b.outcome, short_b.reason) == ("partial", "short_transfer")


@pytest.mark.parametrize("kw,reason", [
    ({"bom": None}, "no_timestamps"), ({"eom": None}, "no_timestamps"),
    ({"seconds": 0.0}, "invalid_duration"), ({"seconds": -3.0}, "invalid_duration"), ({"seconds": 601.0}, "invalid_duration"),
    ({"test_bytes_received": 0}, "no_bytes"), ({"test_bytes_received": None}, "no_bytes"),
    ({"seconds": 3.0, "test_bytes_received": 10**12}, "bytes_exceed_profile"),
    ({"seconds": 8.0, "test_bytes_received": 10_500_001}, "bytes_exceed_profile"),    # just over the 5 % tolerance of a 10 MB profile
    ({"seconds": 8.0, "test_bytes_received": 10_500_000}, None),
])
def test_counters_that_do_not_add_up_give_no_number_at_all(kw, reason):
    c = speed.compute("download", PF, speed.check_counters("download", EP, PF, counters(**kw)))
    if reason is None:   # the edge of the tolerance is still a measurement
        assert c.outcome == "completed" and c.mbps == 10.5
        return
    assert c.outcome == "inconclusive" and c.mbps is None and c.reason == reason   # never 0, never a guess


@pytest.mark.parametrize("state,reason", [("Error_InitConnectionFailed", "device_error"), ("Error_Timeout", "device_error"), ("Requested", "not_completed"), ("None", "not_completed")])
def test_a_device_that_did_not_complete_yields_an_error_and_no_figure(state, reason):
    c = speed.compute("download", PF, speed.check_counters("download", EP, PF, counters(state=state)))
    assert (c.outcome, c.mbps, c.reason) == ("error", None, reason)


@pytest.mark.parametrize("mut", [
    lambda d: {**d, "url": "http://10.0.0.1/x"},                 # a field the shape does not know
    lambda d: {**d, "direction": "upload"},                      # a report for another direction
    lambda d: {**d, "target": "other-node"},                     # a report for another endpoint
    lambda d: {**d, "profile": "200mb"},                         # a report for another profile
    lambda d: {**d, "state": "Completed; DROP"},                 # free text in the state
    lambda d: {**d, "test_bytes_received": -1},
    lambda d: {**d, "test_bytes_received": True},                # a boolean is not a count
    lambda d: {**d, "test_bytes_received": 10**13},
    lambda d: {**d, "bom": "not a time"},
    lambda d: {**d, "bom": "2026-10-31T12:00:00"},               # no zone: cannot be compared with anything
    lambda d: {**d, "http_status": 1000},
    lambda d: {k: v for k, v in d.items() if k != "state"},
    lambda d: "Completed",
    lambda d: None,
])
def test_the_edge_report_is_accepted_only_in_its_exact_shape(mut):
    assert speed.check_counters("download", EP, PF, mut(counters())) is None


def test_catalog_parameters_are_two_logical_names_and_nothing_else():
    ok = {"target": EP, "profile": PF}
    assert bench.params_valid("speed_test_download", ok) and bench.params_valid("speed_test_upload", ok)
    for bad in ({}, {"target": EP}, {"profile": PF}, {**ok, "url": "http://x"}, {"target": "http://10.0.0.1/f", "profile": PF},
                {"target": "10.0.0.1", "profile": PF}, {"target": "Core1", "profile": PF}, {"target": EP, "profile": "1gb"}, {"target": 3, "profile": PF}):
        assert not bench.params_valid("speed_test_download", bad), bad


# ---- setup helpers --------------------------------------------------------------------------------------------------------------------------------
def _speed_flag(migrated, tenant, on=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'speed_diagnostics',:e)"), {"t": tenant, "e": on})


def _endpoint(migrated, seed, eid=EP, kind="CORE", enabled=True, health="ok"):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO speed_endpoints (tenant_id, id, label, target_kind, region, enabled, health, health_at) VALUES (:t,:i,'Nó de teste',:k,'DC-1',:e,:h,now())"),
                  {"t": seed["A"], "i": eid, "k": kind, "e": enabled, "h": health})


def _link(migrated, seed, inv, cpe, pon="SPD/1", olt="OLT-SPD", serial=None):
    """A confirmed ONU<->CPE link whose ONU sits on a PON; the same `olt`/`pon` names share the PON."""
    t = str(seed["A"])
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t})
        o = c.execute(text("SELECT id FROM olts WHERE name = :n"), {"n": olt}).scalar() or c.execute(
            text("INSERT INTO olts (tenant_id, edge_id, name, vendor, model, firmware, support_level) VALUES (:t,:e,:n,'Huawei','MA5608T','R015','observed') RETURNING id"),
            {"t": t, "e": str(inv["a1"]["edge"]), "n": olt}).scalar()
        pid = c.execute(text("SELECT id FROM pon_ports WHERE olt_id = :o AND pon_path = :p"), {"o": o, "p": pon}).scalar() or c.execute(
            text("INSERT INTO pon_ports (tenant_id, olt_id, pon_path) VALUES (:t,:o,:p) RETURNING id"), {"t": t, "o": o, "p": pon}).scalar()
        onu = c.execute(text("INSERT INTO onus (tenant_id, olt_id, pon_id, serial, status) VALUES (:t,:o,:p,:s,'online') RETURNING id"),
                        {"t": t, "o": o, "p": pid, "s": serial or f"HWTCH4{uuid4().hex[:10]}"}).scalar()
        c.execute(text("INSERT INTO onu_cpe_links (tenant_id, onu_id, cpe_id, status, confidence, evidence, reviewed_by, reviewed_at) "
                       "VALUES (:t,:u,:c,'confirmed',0.99,CAST('{\"rule\":\"test\"}' AS jsonb),:r,now())"), {"t": t, "u": onu, "c": cpe, "r": uuid4()})


def _redirect_row(migrated, seed, op=speed.REDIRECT_PROBE):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, verified_at, evidence_ref) "
                       "VALUES (:t,:v,:m,:f,'tr069',:o,'supported','observed',now(),'docs/wiki/bench/speed-redirect-test.md')"),
                  {"t": seed["A"], "v": PROFILE[0], "m": PROFILE[1], "f": PROFILE[2], "o": op})


def _ready(client, seed, inv, migrated, op="speed_test_download", serial="BNCH-CPE-0001", ext="bench-ext-0001", first=True, **kw):
    """Everything open for one bench CPE: flags, endpoint, PON link, registry evidence, redirect evidence, the owner's prior authorization."""
    if first:
        _flag(migrated, seed["A"])
        _speed_flag(migrated, seed["A"])
        _endpoint(migrated, seed)
    cpe = _cpe(client, inv, seed, serial=serial, ext=ext)
    _bench(migrated, seed, inv, cpe, op=op, params=PARAMS, capability=first, **kw)
    if first:
        _redirect_row(migrated, seed)
    return cpe


def _post(client, h, cpe, direction="download", **kw):
    body = {"direction": direction, "endpoint_id": EP, "profile": PF, **kw}
    key = body.pop("key", None)
    return client.post(f"/v1/cpes/{cpe}/speed/runs", headers={**h, "Idempotency-Key": key or uuid4().hex}, json=body)


def _rows(migrated, sql, **a):
    with migrated.begin() as c:
        return c.execute(text(sql), a).all()


# ---- flag, permission, tenant ---------------------------------------------------------------------------------------------------------------------
def test_everything_answers_feature_disabled_while_the_flag_is_off_and_creates_nothing(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    h = hdr(client, "alice", seed, "A")
    for r in (client.get(f"/v1/cpes/{cpe}/speed/capabilities", headers=h), client.get(f"/v1/cpes/{cpe}/speed/runs", headers=h),
              client.get("/v1/speed/health", headers=h), _post(client, h, cpe)):
        assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
    assert _rows(migrated, "SELECT 1 FROM jobs WHERE operation LIKE 'speed_test_%'") == [] and _rows(migrated, "SELECT 1 FROM speed_test_runs") == []


def test_only_the_roles_that_carry_the_permission_can_ask(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    for who in ("dave", "carol"):
        r = _post(client, hdr(client, who, seed, "A"), cpe)
        assert r.status_code == 403, (who, r.text)
    assert _rows(migrated, "SELECT 1 FROM speed_test_runs") == []


def test_the_default_of_the_flag_is_off_and_the_catalog_knows_it():
    from app.core import features
    assert features.FEATURES["speed_diagnostics"] is False


# ---- capabilities screen --------------------------------------------------------------------------------------------------------------------------
def test_a_cpe_outside_the_bench_list_is_never_offered_and_says_why(client, seed, inv, migrated):
    _speed_flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    j = client.get(f"/v1/cpes/{cpe}/speed/capabilities", headers=hdr(client, "alice", seed, "A")).json()
    assert j["bench_target"] is False and j["ready"] is False
    assert {d["reason"] for d in j["directions"].values()} == {"operation_not_homologated"}


def test_the_screen_is_ready_only_with_a_bench_target_registry_evidence_redirect_evidence_and_a_healthy_endpoint(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    j = client.get(f"/v1/cpes/{cpe}/speed/capabilities", headers=hdr(client, "alice", seed, "A")).json()
    assert j["directions"]["download"]["offered"] is True and j["redirect_verified"] is True and j["ready"] is True
    assert j["directions"]["upload"]["reason"] == "capability_not_observed"        # evidence exists for the download only
    assert j["endpoints"][0]["id"] == EP and "url" not in str(j).lower() and "http" not in str(j).lower()   # a logical id, never an address
    assert j["limits"] == {"per_cpe": 1, "per_pon": 1, "per_tenant": 2}


def test_without_redirect_evidence_the_operation_is_not_eligible(client, seed, inv, migrated):
    _flag(migrated, seed["A"]); _speed_flag(migrated, seed["A"]); _endpoint(migrated, seed)
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, op="speed_test_download", params=PARAMS)
    _link(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    assert client.get(f"/v1/cpes/{cpe}/speed/capabilities", headers=h).json()["directions"]["download"]["reason"] == "redirect_unverified"
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "redirect_unverified"
    # the confirmed egress ACL stands in for the 3xx probe, with its own evidence
    _redirect_row(migrated, seed, speed.EGRESS_ACL)
    assert client.get(f"/v1/cpes/{cpe}/speed/capabilities", headers=h).json()["directions"]["download"]["offered"] is True


def test_the_gate_itself_refuses_without_redirect_evidence_even_if_the_screen_check_were_bypassed(client, seed, inv, migrated, monkeypatch):
    _flag(migrated, seed["A"]); _speed_flag(migrated, seed["A"]); _endpoint(migrated, seed)
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, op="speed_test_download", params=PARAMS)
    _link(migrated, seed, inv, cpe)
    real, calls = speed.redirect_verified, {"n": 0}

    def first_call_lies(*a):
        calls["n"] += 1
        return True if calls["n"] == 1 else real(*a)   # the request's own check is fooled; the gate's is not
    monkeypatch.setattr(speed, "redirect_verified", first_call_lies)
    r = _post(client, hdr(client, "alice", seed, "A"), cpe)
    assert r.status_code == 409 and r.json()["reason"] == "redirect_unverified" and calls["n"] >= 2
    assert _rows(migrated, "SELECT status FROM jobs WHERE operation = 'speed_test_download'")[0].status == "CANCELLED"


def test_the_generic_jobs_api_never_creates_a_speed_job(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    for op in ("speed_test_download", "speed_test_upload"):
        r = client.post("/v1/jobs/preview", headers={**hdr(client, "alice", seed, "A"), **idem()}, json={"operation": op, "target_id": cpe, "params": PARAMS})
        assert r.status_code == 409 and r.json()["detail"] == "use_speed_api"
    assert _rows(migrated, "SELECT 1 FROM jobs WHERE operation LIKE 'speed_test_%'") == []


def test_turning_the_flag_off_stops_a_request_made_before(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)    # dispatched already; a second job in the queue would be refused at its next gate
    with migrated.begin() as c:
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE feature = 'speed_diagnostics'"))
    from app.api import jobs as jobs_mod
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        row = jobs_mod._load(c, run["job_id"])
        assert bench.gate(c, seed["A"], row, mode="dispatch") == "speed_disabled"


@pytest.mark.parametrize("detail,kept", [("timeout", "timeout"), ("no_response_from_http://10.1.2.3/f", "edge_error"), ("failed to reach 10.1.2.3:8080", "edge_error"), ("", "edge_error"), (None, None)])
def test_free_text_from_the_edge_never_reaches_the_stored_result_or_the_history(client, seed, inv, migrated, detail, kept):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    body = {"state": "failed", **({"detail": detail} if detail is not None else {})}
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"), json=body).status_code == 204
    stored = _rows(migrated, "SELECT result FROM jobs WHERE id = :j", j=run["job_id"])[0].result
    assert stored["detail"] == kept and "10.1.2.3" not in str(stored)
    got = client.get(f"/v1/cpes/{cpe}/speed/runs/{run['id']}", headers=h).json()
    assert got["status"] == "failed" and got["reason"] == kept and "10.1.2.3" not in str(got)


# ---- the request path -----------------------------------------------------------------------------------------------------------------------------
def test_blockers_are_answered_with_a_status_a_code_and_an_audit_row_and_leave_no_live_job(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    h = hdr(client, "alice", seed, "A")
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json() == {"outcome": "blocked", "reason": "pon_unknown", "run": None}    # no confirmed ONU<->CPE link
    _link(migrated, seed, inv, cpe)
    assert _post(client, h, cpe, endpoint_id="nope-1").json()["reason"] == "endpoint_unavailable"
    with migrated.begin() as c:
        c.execute(text("UPDATE speed_endpoints SET health = 'down'"))
    assert _post(client, h, cpe).json()["reason"] == "endpoint_unhealthy"
    with migrated.begin() as c:
        c.execute(text("UPDATE speed_endpoints SET health = 'ok', enabled = false"))
    assert _post(client, h, cpe).json()["reason"] == "endpoint_unavailable"
    assert _post(client, h, cpe, direction="upload").json()["reason"] == "capability_not_observed"
    assert _rows(migrated, "SELECT 1 FROM jobs WHERE operation LIKE 'speed_test_%'") == []
    why = {r.evidence_redacted["reason"] for r in _rows(migrated, "SELECT evidence_redacted FROM audit_log WHERE action = 'speed.blocked'")}
    assert {"pon_unknown", "endpoint_unavailable", "endpoint_unhealthy", "capability_not_observed"} <= why


def test_a_request_is_a_job_of_the_existing_engine_and_never_leaves_before_an_approval(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    r = _post(client, h, cpe)
    assert r.status_code == 201 and r.json()["outcome"] == "submitted" and r.json()["run"]["status"] == "awaiting_approval"
    run = r.json()["run"]
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204     # nothing is dispatched unapproved
    job = client.get(f"/v1/jobs/{run['job_id']}", headers=h).json()
    assert job["operation"] == "speed_test_download" and job["status"] == "PENDING_APPROVAL" and job["required_approvals"] == 1
    assert _rows(migrated, "SELECT state FROM bench_authorizations")[0].state == "open"               # the authorization is consumed by the approval, not by the request
    assert [a.action for a in _rows(migrated, "SELECT action FROM audit_log WHERE action LIKE 'speed.%'")] == ["speed.requested"]


def test_the_same_key_returns_the_same_run_and_a_different_test_under_it_is_refused(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    k = uuid4().hex
    a = _post(client, h, cpe, key=k)
    b = _post(client, h, cpe, key=k)
    assert a.status_code == 201 and b.status_code == 200 and b.json()["outcome"] == "existing" and b.json()["run"]["id"] == a.json()["run"]["id"]
    assert _post(client, h, cpe, key=k, profile="50mb").status_code == 409
    assert len(_rows(migrated, "SELECT 1 FROM speed_test_runs")) == 1


def test_flag_for_the_edge_half_off_means_the_bench_path_is_not_visible_at_all(client, seed, inv, migrated, monkeypatch):
    monkeypatch.setattr(bench, "SPEED_EDGE_SUPPORT", False)     # the shipped default of this PR
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "operation_not_homologated"
    assert client.get(f"/v1/cpes/{cpe}/speed/capabilities", headers=h).json()["ready"] is False
    assert _rows(migrated, "SELECT 1 FROM speed_test_runs") == []
    assert client.post("/v1/bench/authorizations", headers=h, json={"operation": "speed_test_download", "cpe_id": cpe, "params": PARAMS, "minutes": 30}).status_code == 409


# ---- the full path with a fake Edge ---------------------------------------------------------------------------------------------------------------
def _dispatched(client, seed, inv, migrated, direction="download"):
    op = f"speed_test_{direction}"
    cpe = _ready(client, seed, inv, migrated, op=op)
    _link(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    run = _post(client, h, cpe, direction=direction).json()["run"]
    assert client.post(f"/v1/jobs/{run['job_id']}/approve", headers=_approver(client, seed, migrated)).json()["status"] == "APPROVED"
    env = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    assert env.status_code == 200
    return cpe, h, run, env.json()


def test_the_envelope_carries_two_logical_names_and_no_address(client, seed, inv, migrated):
    _, _, run, env = _dispatched(client, seed, inv, migrated)
    assert env["operation"] == "speed_test_download" and env["params"] == PARAMS and env["authorization_id"]
    blob = str(env).lower()
    assert "http" not in blob and "url" not in blob


def test_a_valid_report_becomes_a_computed_run_the_screen_can_read(client, seed, inv, migrated):
    cpe, h, run, env = _dispatched(client, seed, inv, migrated)
    r = client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"),
                    json={"state": "succeeded", "postcheck_ok": True, "data": counters(seconds=8.0, total_bytes_received=10_001_234)})
    assert r.status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/speed/runs/{run['id']}", headers=h).json()
    assert got["status"] == "completed" and got["mbps"] == 10.0 and got["reliable"] is True and got["bytes"] == 10_000_000 and got["duration_ms"] == 8000
    assert client.get(f"/v1/cpes/{cpe}/speed/runs", headers=h).json()["items"][0]["id"] == run["id"]
    # the raw counters are not kept anywhere: only the computed figures
    assert "total_bytes_received" not in str(_rows(migrated, "SELECT result FROM jobs WHERE id = :j", j=run["job_id"])[0].result)
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is False


def test_a_report_re_sent_after_a_lost_acknowledgement_changes_nothing(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    rep = {"state": "succeeded", "postcheck_ok": True, "data": counters(seconds=8.0)}
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"), json=rep).status_code == 204
    again = {**rep, "data": counters(seconds=1.0)}
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"), json=again).status_code == 204
    assert client.get(f"/v1/cpes/{cpe}/speed/runs/{run['id']}", headers=h).json()["mbps"] == 10.0


def test_a_device_error_is_a_clear_result_not_a_failed_write(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    d = {"direction": "download", "target": EP, "profile": PF, "state": "Error_InitConnectionFailed"}
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"), json={"state": "succeeded", "postcheck_ok": True, "data": d}).status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/speed/runs/{run['id']}", headers=h).json()
    assert got["status"] == "error" and got["mbps"] is None and got["reason"] == "device_error"      # "—", never 0
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is False


@pytest.mark.parametrize("data", [None, {}, {**counters(), "extra": 1}, counters("upload"), {**counters(), "target": "other-node"}, {**counters(), "profile": "50mb"}])
def test_a_success_without_the_exact_counters_of_this_job_is_a_failure_and_locks_the_target(client, seed, inv, migrated, data):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    body = {"state": "succeeded", "postcheck_ok": True, **({"data": data} if data is not None else {})}
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"), json=body).status_code == 204
    got = client.get(f"/v1/cpes/{cpe}/speed/runs/{run['id']}", headers=h).json()
    assert got["status"] == "failed" and got["mbps"] is None and got["reason"] == "invalid_result"
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is True


def test_an_uncertain_outcome_is_unknown_and_locks_the_target_and_data_rides_only_with_a_success(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    r = client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"), json={"state": "failed", "data": counters()})
    assert r.status_code == 422
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"), json={"state": "succeeded", "postcheck_ok": False}).status_code == 204
    assert client.get(f"/v1/cpes/{cpe}/speed/runs/{run['id']}", headers=h).json()["status"] == "unknown"
    assert _rows(migrated, "SELECT write_locked FROM bench_targets")[0].write_locked is True


# ---- limits ---------------------------------------------------------------------------------------------------------------------------------------
def test_one_test_per_ont_then_the_slot_comes_back_when_the_job_ends(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "cpe_busy"
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"),
                       json={"state": "succeeded", "postcheck_ok": True, "data": counters()}).status_code == 204
    assert _post(client, h, cpe).json()["reason"] != "cpe_busy"       # the slot is free again (whatever the gate then says about the target)


def _second(client, seed, inv, migrated, n, pon, olt="OLT-SPD"):
    cpe = _ready(client, seed, inv, migrated, serial=f"BNCH-CPE-000{n}", ext=f"bench-ext-000{n}", first=False)
    _link(migrated, seed, inv, cpe, pon=pon, olt=olt)
    return cpe


def test_one_test_per_pon_and_two_per_provider(client, seed, inv, migrated):
    c1 = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, c1, pon="SPD/1")
    h = hdr(client, "alice", seed, "A")
    assert _post(client, h, c1).status_code == 201
    c2 = _second(client, seed, inv, migrated, 2, "SPD/1")                       # same PON
    assert _post(client, h, c2).json()["reason"] == "pon_busy"
    c3 = _second(client, seed, inv, migrated, 3, "SPD/2")                       # another PON: the second slot of the provider
    assert _post(client, h, c3).status_code == 201
    c4 = _second(client, seed, inv, migrated, 4, "SPD/3")                       # a third PON: the provider's limit
    assert _post(client, h, c4).json()["reason"] == "tenant_busy"
    assert len(_rows(migrated, "SELECT 1 FROM speed_test_runs")) == 2


def test_a_suggested_link_does_not_count_as_a_pon(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    with migrated.begin() as c:
        c.execute(text("UPDATE onu_cpe_links SET status = 'suggested', reviewed_by = NULL, reviewed_at = NULL"))
    assert _post(client, hdr(client, "alice", seed, "A"), cpe).json()["reason"] == "pon_unknown"


def test_the_second_direction_joins_the_group_of_the_first_and_only_that(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"),
                       json={"state": "succeeded", "postcheck_ok": True, "data": counters()}).status_code == 204
    assert _post(client, h, cpe, direction="upload", group_id=str(uuid4())).json()["reason"] == "group_mismatch"          # a group that does not exist
    assert _post(client, h, cpe, direction="download", group_id=run["group_id"]).json()["reason"] == "group_mismatch"     # the same direction twice
    assert _post(client, h, cpe, direction="upload", group_id=run["group_id"], profile="50mb").json()["reason"] == "group_mismatch"


# ---- isolation and storage ------------------------------------------------------------------------------------------------------------------------
def test_runs_and_endpoints_are_isolated_by_tenant_and_the_app_role_cannot_create_endpoints(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    hb = hdr(client, "bob", seed, "B")
    assert client.get(f"/v1/cpes/{cpe}/speed/runs", headers=hb).status_code in (403, 404)
    assert client.get(f"/v1/cpes/{cpe}/speed/runs/{run['id']}", headers=hb).status_code in (403, 404)
    from app.core.db import get_engine
    with pytest.raises(DBAPIError):
        with get_engine().begin() as c:   # the application role: no INSERT on the endpoint catalog (only the owner CLI writes it)
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text("INSERT INTO speed_endpoints (tenant_id, id, label, target_kind, region) VALUES (:t,'x-node-1','x','CORE','r')"), {"t": seed["A"]})


@pytest.mark.parametrize("sql", [
    "INSERT INTO speed_endpoints (tenant_id, id, label, target_kind, region) VALUES (:t,'Bad_Id','x','CORE','r')",
    "INSERT INTO speed_endpoints (tenant_id, id, label, target_kind, region) VALUES (:t,'ok-node','x','WAN','r')",
    "INSERT INTO speed_endpoints (tenant_id, id, label, target_kind, region, health) VALUES (:t,'ok-node','x','CORE','r','great')",
    "INSERT INTO speed_endpoints (tenant_id, id, label, target_kind, region) VALUES (:t,'http-10-0-0-1','x','CORE','http://10.0.0.1')",
])
def test_the_endpoint_catalog_refuses_anything_that_is_not_a_logical_name(migrated, seed, sql):
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(sql), {"t": seed["A"]})


def test_the_catalog_has_no_column_that_could_hold_an_address(migrated):
    cols = {r.column_name for r in _rows(migrated, "SELECT column_name FROM information_schema.columns WHERE table_name IN ('speed_endpoints','speed_test_runs')")}
    assert not {c for c in cols if any(w in c for w in ("url", "host", "addr", "ip", "token", "secret", "password", "payload"))}, cols


def test_the_run_row_cannot_carry_a_figure_without_a_measurement_or_a_zero(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    for sql in ("UPDATE speed_test_runs SET outcome = 'error', completed_at = now(), mbps = 5",
                "UPDATE speed_test_runs SET outcome = 'completed', completed_at = now()",
                "UPDATE speed_test_runs SET outcome = 'completed', completed_at = now(), mbps = 0, bytes = 1, duration_ms = 1",
                "UPDATE speed_test_runs SET mbps = 5"):
        with pytest.raises(DBAPIError):
            with migrated.begin() as c:
                c.execute(text(sql))


# ---- owner CLI ------------------------------------------------------------------------------------------------------------------------------------
def test_owner_cli_manages_logical_endpoints_and_records_the_redirect_evidence(client, seed, inv, migrated, admin_url, monkeypatch, tmp_path):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(seed["A"])
    for bad in ("http://10.0.0.1", "Core1", "a", "10.0.0.1/x"):
        with pytest.raises(SystemExit):
            cli.main(["speed-endpoint-set", t, bad, "Nó", "CORE", "DC-1", "on"])
    with pytest.raises(SystemExit, match="label"):
        cli.main(["speed-endpoint-set", t, "core-sp-9", "http://10.0.0.1/f", "CORE", "DC-1", "on"])
    cli.main(["speed-endpoint-set", t, "core-sp-9", "Nó do core", "CORE", "DC-1", "on"])
    cli.main(["speed-endpoint-set", t, "core-sp-9", "Nó do core", "CORE", "DC-1", "off"])
    row = _rows(migrated, "SELECT enabled, health FROM speed_endpoints WHERE id = 'core-sp-9'")[0]
    assert row.enabled is False and row.health == "unknown"       # a new endpoint is never healthy until the Edge says so
    # the redirect observation is a registry row: it needs evidence like any claim
    with pytest.raises(SystemExit, match="evidence"):
        cli.main(["capability-set", t, PROFILE[0], PROFILE[1], PROFILE[2], "tr069", speed.REDIRECT_PROBE, "supported", "observed"])
    cli.main(["capability-set", t, PROFILE[0], PROFILE[1], PROFILE[2], "tr069", speed.REDIRECT_PROBE, "supported", "observed",
              "--evidence", "docs/wiki/bench/speed-redirect-test.md", "--verified-at", datetime.now(UTC).isoformat()])
    assert _rows(migrated, "SELECT 1 FROM device_capabilities WHERE operation = :o", o=speed.REDIRECT_PROBE)
    # a speed authorization can be recorded only with the two logical names, and only once the Edge half exists
    cpe = _cpe(client, inv, seed)
    cli.main(["bench-target-add", t, cpe, str(inv["a1"]["edge"])])
    now = datetime.now(UTC)
    args = ["bench-authorize", t, "speed_test_download", cpe, "--from", (now - timedelta(minutes=1)).isoformat(), "--to", (now + timedelta(minutes=30)).isoformat(), "--by", "responsavel"]
    with pytest.raises(SystemExit, match="parameters outside"):
        cli.main(args)
    with pytest.raises(SystemExit, match="parameters outside"):
        cli.main([*args, "--speed-target", "http://10.0.0.1/f", "--speed-profile", PF])
    cli.main([*args, "--speed-target", EP, "--speed-profile", PF])
    monkeypatch.setattr(bench, "SPEED_EDGE_SUPPORT", False)
    with pytest.raises(SystemExit, match="not delivered"):
        cli.main([*args, "--speed-target", EP, "--speed-profile", PF])


def _upload_evidence(migrated, seed, cpe):
    with migrated.begin() as c:   # the upload has its own registry evidence and its own single-use authorization
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, verified_at, evidence_ref) "
                       "VALUES (:t,:v,:m,:f,'tr069','speed_test_upload','supported','observed',now(),'docs/wiki/bench/speed-upload-test.md')"),
                  {"t": seed["A"], "v": PROFILE[0], "m": PROFILE[1], "f": PROFILE[2]})
        c.execute(text("INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by) "
                       "VALUES (:t,'speed_test_upload',:c,:h,now() - interval '1 minute',now() + interval '30 minutes','responsavel')"),
                  {"t": seed["A"], "c": cpe, "h": bench.params_hash(PARAMS)})


def test_the_upload_that_follows_the_download_of_the_same_test_joins_its_group(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"),
                       json={"state": "succeeded", "postcheck_ok": True, "data": counters()}).status_code == 204
    _upload_evidence(migrated, seed, cpe)
    r = _post(client, h, cpe, direction="upload", group_id=run["group_id"])
    assert r.status_code == 201 and r.json()["run"]["group_id"] == run["group_id"] and r.json()["run"]["direction"] == "upload"


def test_a_group_never_holds_the_same_direction_twice_even_after_the_first_ended(client, seed, inv, migrated):
    cpe, h, run, _ = _dispatched(client, seed, inv, migrated)
    assert client.post(f"/v1/edge/jobs/{run['job_id']}/result", headers=agent(client, inv, "a1"),
                       json={"state": "succeeded", "postcheck_ok": True, "data": counters()}).status_code == 204
    _upload_evidence(migrated, seed, cpe)
    assert _post(client, h, cpe, direction="upload", group_id=run["group_id"]).status_code == 201
    up = _rows(migrated, "SELECT job_id FROM speed_test_runs WHERE direction = 'upload'")[0].job_id
    with migrated.begin() as c:   # the upload ended too: the slot is free, the group is complete
        c.execute(text("UPDATE jobs SET status = 'CANCELLED' WHERE id = :j"), {"j": up})
    for d in ("download", "upload"):
        assert _post(client, h, cpe, direction=d, group_id=run["group_id"]).json()["reason"] == "group_mismatch"
    with pytest.raises(DBAPIError):   # and the database refuses it on its own
        with migrated.begin() as c:
            c.execute(text("INSERT INTO speed_test_runs (tenant_id, cpe_id, job_id, group_id, direction, endpoint_id, profile, pon_id, requested_by) "
                           "SELECT tenant_id, cpe_id, job_id, group_id, direction, endpoint_id, profile, pon_id, requested_by FROM speed_test_runs LIMIT 1"))
