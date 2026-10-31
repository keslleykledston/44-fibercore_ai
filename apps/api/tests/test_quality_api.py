"""QoS-001 (ADR-0039), the API: flag, RBAC, tenant isolation, idempotency, the read built from stored data, the reference to SD-001, immutability and audit."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import features
from tests.conftest import hdr
from tests.test_jobs_bench import _cleanup as _bench_cleanup  # noqa: F401  (autouse: bench lists, authorizations, registry, CPEs)
from tests.test_jobs_bench import _cpe
from tests.test_speed import (
    _link,
    _post,
    _ready,
    _rows,
    _speed_cleanup,  # noqa: F401  (autouse: runs, endpoints, jobs)
)


@pytest.fixture(autouse=True)
def _quality_cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM quality_runs"))
        c.execute(text("DELETE FROM cpe_state"))
        c.execute(text("DELETE FROM audit_log WHERE action LIKE 'quality.%'"))
        c.execute(text("DELETE FROM tenant_features WHERE feature LIKE 'quality_%'"))


def _flags(migrated, seed, *names, on=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        for n in names:
            c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,:e)"), {"t": seed["A"], "f": n, "e": on})


def _state(migrated, seed, cpe, rows, age_s=60):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        at = datetime.now(UTC) - timedelta(seconds=age_s)
        for metric, scope, value in rows:
            c.execute(text("INSERT INTO cpe_state (tenant_id, cpe_id, metric, scope, value, captured_at, observed_at) VALUES (:t,:c,:m,:s,CAST(:v AS jsonb),:a,:a)"),
                      {"t": seed["A"], "c": cpe, "m": metric, "s": scope, "v": json.dumps(value), "a": at})


GOOD = [("wan_link_status", "link/1", "Up"), ("wan_connection_status", "ppp/3/1", "Connected"), ("uptime_seconds", "ppp/3/1", 4321),
        ("wifi_radio_enabled", "radio/1", "Enabled"), ("wifi_channel", "radio/1", 6)]


def _onu(migrated, seed, cpe, status="online", rx=-19.5, age_s=120):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE onus SET status = :s, rx_dbm = :r, observed_at = now() - make_interval(secs => :a) "
                       "WHERE id IN (SELECT onu_id FROM onu_cpe_links WHERE cpe_id = :c)"), {"s": status, "r": rx, "a": age_s, "c": cpe})


def _go(client, inv, seed, migrated, flags=("quality_diagnostics",), **kw):
    _flags(migrated, seed, *flags)
    cpe = _cpe(client, inv, seed, **kw)
    return cpe, hdr(client, "alice", seed, "A")


def run(client, h, cpe, mode="quick", key=None, **body):
    return client.post(f"/v1/cpes/{cpe}/quality/runs", headers={**h, "Idempotency-Key": key or uuid4().hex}, json={"mode": mode, **body})


def test_Q19_everything_answers_feature_disabled_while_the_flag_is_off_and_creates_nothing(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    h = hdr(client, "alice", seed, "A")
    assert features.FEATURES["quality_diagnostics"] is features.FEATURES["quality_full"] is features.FEATURES["quality_active_tests"] is False
    for r in (client.get(f"/v1/cpes/{cpe}/quality/capabilities", headers=h), client.get(f"/v1/cpes/{cpe}/quality/runs", headers=h), run(client, h, cpe),
              client.get(f"/v1/cpes/{cpe}/quality/runs/{uuid4()}", headers=h)):
        assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
    assert _rows(migrated, "SELECT count(*) AS n FROM quality_runs")[0].n == 0


def test_a_quick_read_is_built_from_the_stored_data_and_says_where_each_figure_came_from(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    _link(migrated, seed, inv, cpe)
    _state(migrated, seed, cpe, GOOD)
    _onu(migrated, seed, cpe)
    r = run(client, h, cpe)
    assert r.status_code == 201, r.text
    d = r.json()
    ms = {(m["id"], m["instance"]): m for m in d["metrics"]}
    assert d["mode"] == "quick" and d["state"] in ("completed", "partial") and d["hypotheses"] == []
    assert ms[("wan.link_status", "link/1")]["value"] == "Up" and ms[("wan.link_status", "link/1")]["scope"] == "WAN_UNCLASSIFIED"
    assert ms[("optical.rx_dbm", None)]["source"] == "OLT_ADAPTER" and ms[("optical.rx_dbm", None)]["value"] == -19.5
    assert ms[("cpe.uptime_s", "ppp/3/1")]["unit"] == "s" and ms[("wifi.channel", "radio/1")]["value"] == 6
    assert d["summary"]["state"] == "no_anomalies_observed"
    # nothing identifying travels or is stored: no serial, address, SSID or MAC
    blob = json.dumps(d)
    assert "HWTC" not in blob and "ssid" not in blob.lower()
    got = client.get(f"/v1/cpes/{cpe}/quality/runs/{d['id']}", headers=h).json()
    assert got == d and client.get(f"/v1/cpes/{cpe}/quality/runs", headers=h).json()["runs"][0]["id"] == d["id"]


def test_without_any_data_the_read_is_insufficient_data_and_every_figure_is_null(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    d = run(client, h, cpe).json()
    assert d["state"] == "partial" and d["summary"]["state"] == "insufficient_data" and all(m["value"] is None for m in d["metrics"])


def test_an_old_reading_is_shown_as_history_and_does_not_count_as_current(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    _state(migrated, seed, cpe, [("wan_link_status", "link/1", "Down")], age_s=7200)
    d = run(client, h, cpe).json()
    m = next(m for m in d["metrics"] if m["id"] == "wan.link_status")
    assert m["status"] == "stale" and m["freshness_s"] >= 7200 and d["summary"]["observations"] == [] and d["summary"]["state"] == "insufficient_data"


def test_an_observed_failure_is_attention_with_its_reason(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    _link(migrated, seed, inv, cpe)
    _state(migrated, seed, cpe, [("wan_link_status", "link/1", "Down")])
    _onu(migrated, seed, cpe, status="offline", rx=None)
    d = run(client, h, cpe).json()
    assert d["summary"]["state"] == "attention" and {o["code"] for o in d["summary"]["observations"]} == {"WAN_LINK_DOWN", "ONU_NOT_ONLINE"}


def test_Q08_roles_and_tenants(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    dave, carol, bob = hdr(client, "dave", seed, "A"), hdr(client, "carol", seed, "A"), hdr(client, "bob", seed, "B")
    assert run(client, dave, cpe).status_code == 201                                       # NOC N1: the quick read
    assert run(client, carol, cpe).status_code == 403                                      # auditor: no operational power
    assert client.get(f"/v1/cpes/{cpe}/quality/runs", headers=carol).status_code == 403
    assert run(client, dave, cpe, mode="full").status_code == 403                          # the complete read is not N1's
    rid = run(client, h, cpe).json()["id"]
    assert client.get(f"/v1/cpes/{cpe}/quality/runs/{rid}", headers=bob).status_code in (403, 404)   # another provider: nothing leaks
    assert client.get(f"/v1/cpes/{cpe}/quality/runs", headers=bob).status_code in (403, 404)
    assert run(client, bob, cpe).status_code in (403, 404)
    from app.core.db import get_engine
    with get_engine().begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
        assert c.execute(text("SELECT count(*) FROM quality_runs")).scalar() == 0


def test_the_same_key_returns_the_same_read_and_another_read_under_it_is_refused(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated, flags=("quality_diagnostics", "quality_full"))
    a = run(client, h, cpe, key="same-key-0001")
    b = run(client, h, cpe, key="same-key-0001")
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    assert run(client, h, cpe, mode="full", key="same-key-0001").status_code == 409
    assert _rows(migrated, "SELECT count(*) AS n FROM quality_runs")[0].n == 1


def test_the_complete_mode_needs_its_own_flag_and_its_own_permission(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    r = run(client, h, cpe, mode="full")
    assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
    assert client.get(f"/v1/cpes/{cpe}/quality/capabilities", headers=h).json()["modes"]["full"] == {"offered": False, "reason": "feature_disabled"}
    _flags(migrated, seed, "quality_full")
    d = run(client, h, cpe, mode="full").json()
    sp = next(m for m in d["metrics"] if m["id"] == "speed.download_mbps")
    assert sp["status"] == "not_available" and sp["details"]["reason"] == "no_speed_run_referenced" and sp["source"] == "SD001" and d["speed_group_ids"] == []
    assert run(client, h, cpe, speed_group_id=str(uuid4())).status_code == 422          # a group only makes sense in the complete mode


def test_Q09_the_complete_mode_references_the_existing_sd001_run_and_never_starts_one(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    _flags(migrated, seed, "quality_diagnostics", "quality_full")
    h = hdr(client, "alice", seed, "A")
    jobs_before = _rows(migrated, "SELECT count(*) AS n FROM jobs")[0].n
    sr = _post(client, h, cpe).json()["run"]                                            # SD-001 starts it, by ITS own flow
    jobs_mid = _rows(migrated, "SELECT count(*) AS n FROM jobs")[0].n
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE speed_test_runs SET outcome = 'completed', mbps = 412.50, bytes = 10000000, duration_ms = 194, basis = 'test_bytes_received', "
                       "completed_at = now() WHERE id = :i"), {"i": sr["id"]})
    d = run(client, h, cpe, mode="full", speed_group_id=sr["group_id"])
    assert d.status_code == 201, d.text
    d = d.json()
    m = next(m for m in d["metrics"] if m["id"] == "speed.download_mbps")
    assert m["value"] == 412.5 and m["source"] == "SD001" and m["evidence_ref"] == f"speed-run:{sr['id']}" and m["group"] == "CORE"
    assert d["speed_group_ids"] == [sr["group_id"]]
    assert _rows(migrated, "SELECT count(*) AS n FROM jobs")[0].n == jobs_mid >= jobs_before   # the quality read created NO job: same run, no second engine
    assert run(client, h, cpe, mode="full", speed_group_id=str(uuid4())).status_code == 422     # unknown group
    other = _cpe(client, inv, seed, serial="OTHER-CPE-0002", ext="other-ext-0002")
    assert run(client, h, other, mode="full", speed_group_id=sr["group_id"]).status_code == 422   # a group of ANOTHER CPE is not referenceable


def test_the_audit_trail_has_who_what_and_outcome_but_no_figure(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    _state(migrated, seed, cpe, GOOD)
    rid = run(client, h, cpe).json()["id"]
    a = _rows(migrated, "SELECT actor_id, target_type, target_id, evidence_redacted FROM audit_log WHERE action = 'quality.requested'")
    assert len(a) == 1 and str(a[0].target_id) == str(cpe) and a[0].evidence_redacted["run_id"] == rid and a[0].actor_id is not None
    assert set(a[0].evidence_redacted) == {"run_id", "mode", "state", "metrics", "hypotheses"}


def test_a_read_is_immutable_and_the_application_role_cannot_change_or_erase_it(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    run(client, h, cpe)
    from app.core.db import get_engine
    for sql in ("UPDATE quality_runs SET state = 'failed'", "DELETE FROM quality_runs", "UPDATE quality_runs SET metrics = '[]'::jsonb"):
        with pytest.raises(DBAPIError), get_engine().begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(sql))


def test_the_capabilities_say_that_active_tests_are_not_offered(client, seed, inv, migrated):
    cpe, h = _go(client, inv, seed, migrated)
    c = client.get(f"/v1/cpes/{cpe}/quality/capabilities", headers=h).json()
    assert c["active_tests"] == {"offered": False, "reason": "not_available"} and c["modes"]["quick"]["offered"] is True and c["speed"] == {"reference_only": True}


def test_the_quality_router_cannot_reach_the_device_or_the_acs():
    import inspect

    from app.api import quality
    src = inspect.getsource(quality)
    for banned in ("jobs.create_preview", "bench.", "requests.", "httpx", "7557", "nbi", "edge_commands"):
        assert banned not in src, banned
