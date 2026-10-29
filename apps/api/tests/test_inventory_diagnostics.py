"""Deterministic diagnostic rules (FC22-006): the extracted R-D001 v1 is the SAME decision the correlator used, runs are read-only,
versioned, reproducible from their stored inputs, tenant-isolated and append-only."""
import ast
import json
import random
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import diagnostics
from tests.conftest import _now, agent, hdr, snap

NAME = "OLT-DG-"


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features"))
        c.execute(text("DELETE FROM diagnostic_runs"))
        c.execute(text("DELETE FROM incident_onus WHERE onu_id IN (SELECT id FROM onus WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-DG-%'))"))
        c.execute(text("DELETE FROM incidents WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-DG-%')"))
        c.execute(text("DELETE FROM onus WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-DG-%')"))
        c.execute(text("DELETE FROM pon_ports WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-DG-%')"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-DG-%'"))


def _on(migrated, tenant):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'diagnostic_engine',true)"), {"t": tenant})


def _push(client, inv, key, name, items, observed, pons=("0/1/0",)):
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, key),
                    json=snap(inv, key, name=name, observed=observed, onus=items,
                              pons=[{"pon_path": p, "status": "up", "complete": True} for p in pons]))
    assert r.status_code == 202, r.text


def _drop_scenario(client, inv, name, n=10, observed_healthy=-600, observed_drop=-540, key="a1"):
    """n ONUs online, then all but one drop (los) together: a PON-wide event."""
    ok = [{"serial": f"{name}-{i:02d}", "pon_path": "0/1/0", "status": "online", "rx_dbm": -20.0} for i in range(n)]
    bad = [ok[0]] + [{**o, "status": "los", "rx_dbm": None} for o in ok[1:]]
    _push(client, inv, key, name, ok, _now(observed_healthy))
    _push(client, inv, key, name, bad, _now(observed_drop))


def _olt_id(client, h, name):
    return next(o["id"] for o in client.get("/v1/olts?limit=1000", headers=h).json() if o["name"] == name)


# ---- the rule itself (pure) -----------------------------------------------------------------------------------------------------------
def _row(**kw):
    base = {"pon_path": "0/1/0", "online": 0, "recent_drops": 0, "los": 0, "dying_gasp": 0, "chronic": 0, "observed": 0, "fresh_data": True}
    base.update(kw)
    base["observed"] = max(base["observed"], base["online"] + base["recent_drops"] + base["chronic"])
    return base


def test_r_d001_thresholds_chronic_and_freshness():
    f = diagnostics.r_d001_v1
    assert f(_row(online=1, recent_drops=5)).matched and f(_row(online=1, recent_drops=5)).finding["status"] == "inferred"
    assert not f(_row(online=0, recent_drops=4)).matched                   # fewer than MIN_DROPPED
    assert f(_row(online=2, recent_drops=8)).matched                       # ratio exactly 0.8
    assert not f(_row(online=3, recent_drops=8)).matched                   # 0.727
    assert f(_row(online=1, recent_drops=5, chronic=500)).matched          # chronically offline ONUs are in neither side
    stale = f(_row(online=1, recent_drops=9, fresh_data=False))
    assert not stale.matched and stale.finding["status"] == "unknown" and stale.finding["hypothesis"] is None
    empty = f(_row())
    assert not empty.matched and empty.finding["status"] == "unknown"
    calm = f(_row(online=20, recent_drops=1))
    assert calm.finding["status"] == "observed" and calm.finding["hypothesis"] is None
    assert f(_row(online=1, recent_drops=5)).finding["requires_human_confirmation"] is True


def test_r_d001_v1_is_the_decision_the_correlator_used_before_the_extraction():
    """Property check against the ORIGINAL inline formula (copied verbatim from the pre-extraction noc.py)."""
    rnd = random.Random(20261029)  # noqa: S311 (deterministic test data, not security)
    for _ in range(2000):
        online, drops, los = rnd.randint(0, 40), rnd.randint(0, 40), rnd.randint(0, 40)
        los, dg = min(los, drops), rnd.randint(0, max(0, drops - 0))
        dg = min(dg, drops - min(los, drops))
        population = online + drops
        ratio = drops / population if population else 0.0
        legacy = drops >= 5 and ratio >= 0.8
        legacy_cause = "fiber_or_los" if los >= drops / 2 else ("power" if dg >= drops / 2 else "unknown")
        res = diagnostics.r_d001_v1(_row(online=online, recent_drops=drops, los=los, dying_gasp=dg))
        assert res.matched == legacy, (online, drops)
        if legacy:
            assert res.suspected_cause == legacy_cause and res.finding["evidence"]["ratio"] == round(ratio, 3)


def test_rules_are_deterministic_versioned_and_pure():
    rows = [{**_row(online=1, recent_drops=6, los=6, observed=7), "subject_id": "p1"}, {**_row(online=9), "subject_id": "p2"}]
    rule = diagnostics.latest("R-D001")
    assert rule is not None and rule.version == 1 and ("R-D001", 1) in diagnostics.RULES
    first, second = diagnostics.run(rule, rows), diagnostics.run(rule, rows)
    assert first == second and json.loads(json.dumps(first)) == first       # same inputs -> same findings, all JSON-native
    assert [f["finding_id"] for f in first] == ["R-D001/v1/p1", "R-D001/v1/p2"]
    assert first[0]["evidence_refs"] == [{"type": "pon", "id": "p1"}] and first[0]["rule_version"] == 1
    assert diagnostics.latest("R-D999") is None
    # purity: the rule module may not reach the clock, the database, the network or randomness
    src = Path(diagnostics.__file__).read_text(encoding="utf-8")
    imported = {n.module.split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
                for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert imported <= {"__future__", "collections", "dataclasses"}, imported


# ---- the API ---------------------------------------------------------------------------------------------------------------------------
def test_everything_is_off_by_default(client, seed):
    h = hdr(client, "alice", seed, "A")
    for method, url, kw in (("get", "/v1/diagnostics/rules", {}), ("post", "/v1/diagnostics/runs", {"json": {"rule_id": "R-D001"}}),
                            ("get", "/v1/diagnostics/runs/00000000-0000-0000-0000-000000000000", {})):
        r = getattr(client, method)(url, headers=h, **kw)
        assert r.status_code == 403 and r.json()["detail"] == "feature_disabled", url


def test_run_finds_the_pon_event_is_read_only_and_persisted(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    _drop_scenario(client, inv, NAME + "1")
    olt = _olt_id(client, h, NAME + "1")
    with migrated.begin() as c:
        before = c.execute(text("SELECT (SELECT count(*) FROM incidents), (SELECT count(*) FROM onus), (SELECT count(*) FROM events_outbox)")).one()
    r = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "olt_id": olt})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["rule_id"] == "R-D001" and d["rule_version"] == 1 and d["truncated"] is False and len(d["findings"]) == 1
    f = d["findings"][0]
    assert f["status"] == "inferred" and f["suspected_cause"] == "fiber_or_los" and f["requires_human_confirmation"] is True
    assert f["evidence"]["onus_down_recent"] == 9 and f["evidence"]["online"] == 1 and f["evidence"]["ratio"] == 0.9
    assert f["evidence_refs"][0]["type"] == "pon" and "OLT-DG" not in json.dumps(f["evidence"])
    with migrated.begin() as c:  # a run observes: no incident, no ONU change, no event out
        after = c.execute(text("SELECT (SELECT count(*) FROM incidents), (SELECT count(*) FROM onus), (SELECT count(*) FROM events_outbox)")).one()
        assert after == before
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'diagnostics.run' AND target_id = :i"), {"i": d["run_id"]}).scalar() == 1
    got = client.get(f"/v1/diagnostics/runs/{d['run_id']}", headers=h).json()
    assert got["findings"] == d["findings"] and got["reproducible"] is True and got["rule_version"] == 1


def test_stale_data_is_unknown_never_a_claim(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    _drop_scenario(client, inv, NAME + "2", observed_healthy=-7200, observed_drop=-6900)  # newest observation ~1h55 old
    olt = _olt_id(client, h, NAME + "2")
    f = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "olt_id": olt}).json()["findings"][0]
    assert f["status"] == "unknown" and f["hypothesis"] is None and "too old" in f["reason"]


def test_replay_detects_tampering_and_unknown_versions_are_rejected(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    _drop_scenario(client, inv, NAME + "3")
    olt = _olt_id(client, h, NAME + "3")
    run = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "rule_version": 1, "olt_id": olt}).json()
    with migrated.begin() as c:  # an owner edits the stored findings: the replay must notice
        c.execute(text("UPDATE diagnostic_runs SET findings = jsonb_set(findings, '{0,status}', '\"observed\"') WHERE id = :i"), {"i": run["run_id"]})
    assert client.get(f"/v1/diagnostics/runs/{run['run_id']}", headers=h).json()["reproducible"] is False
    assert client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "rule_version": 2}).status_code == 404
    assert client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D999"}).status_code == 404
    assert client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "bogus"}).status_code == 422
    assert client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "extra": 1}).status_code == 422
    assert client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "olt_id": "not-a-uuid"}).status_code == 422
    assert client.get("/v1/diagnostics/runs/00000000-0000-0000-0000-000000000000", headers=h).status_code == 404


def test_rules_listing_rbac_and_isolation(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    ha, hd, hb = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A"), hdr(client, "bob", seed, "B")
    rules = client.get("/v1/diagnostics/rules", headers=ha).json()
    assert [(x["id"], x["version"], x["read_only"]) for x in rules] == [("R-D001", 1, True)]
    assert client.get("/v1/diagnostics/rules", headers=hd).status_code == 200                       # noc_n1 reads
    assert client.post("/v1/diagnostics/runs", headers=hd, json={"rule_id": "R-D001"}).status_code == 403   # but does not run
    assert client.post("/v1/diagnostics/runs", headers=agent(client, inv, "a1"), json={"rule_id": "R-D001"}).status_code == 403
    assert client.post("/v1/diagnostics/runs", json={"rule_id": "R-D001"}).status_code == 401
    _drop_scenario(client, inv, NAME + "4")
    run = client.post("/v1/diagnostics/runs", headers=ha, json={"rule_id": "R-D001", "olt_id": _olt_id(client, ha, NAME + "4")}).json()
    _on(migrated, seed["B"])
    assert client.get(f"/v1/diagnostics/runs/{run['run_id']}", headers=hb).status_code == 404       # RLS: B cannot read A's run
    rb = client.post("/v1/diagnostics/runs", headers=hb, json={"rule_id": "R-D001"}).json()
    assert all(NAME not in json.dumps(f) for f in rb["findings"])                                     # nor see A's network in its own run


def test_scope_is_bounded_and_says_when_it_cut(client, seed, inv, migrated, monkeypatch):
    from app.api import diagnostics as api
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    ok = [{"serial": f"{NAME}5-{i}", "pon_path": p, "status": "online", "rx_dbm": -20.0} for i, p in enumerate(("0/1/0", "0/1/1"))]
    _push(client, inv, "a1", NAME + "5", ok, _now(-30), pons=("0/1/0", "0/1/1"))
    olt = _olt_id(client, h, NAME + "5")
    monkeypatch.setattr(api, "MAX_PONS", 1)
    d = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "olt_id": olt}).json()
    assert d["truncated"] is True and len(d["findings"]) == 1
    monkeypatch.setattr(api, "MAX_PONS", 200)
    d = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "olt_id": olt}).json()
    assert d["truncated"] is False and len(d["findings"]) == 2 and all(f["status"] == "observed" for f in d["findings"])


def test_runs_are_append_only_and_tenant_isolated_in_the_database(client, seed, migrated):
    from app.core.db import get_engine, scoped_connection
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    run = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001"}).json()
    for stmt in ("UPDATE diagnostic_runs SET findings = '[]'::jsonb", "DELETE FROM diagnostic_runs"):
        with pytest.raises(DBAPIError), scoped_connection(get_engine(), tenant_id=seed["A"]) as c:
            c.execute(text(stmt))
    with migrated.begin() as c:
        rel = c.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'diagnostic_runs'")).one()
        assert tuple(rel) == (True, True)
        for bad in ("R-X001", "r-d001", "R-D01"):
            with pytest.raises(DBAPIError), c.begin_nested():
                c.execute(text("INSERT INTO diagnostic_runs (tenant_id, rule_id, rule_version, inputs, findings, requested_by) "
                               "VALUES (:t,:r,1,'[]','[]',:u)"), {"t": seed["A"], "r": bad, "u": seed["alice"]})
    assert run["run_id"]


def test_run_scoped_by_onu_resolves_its_pon_server_side(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    ok = [{"serial": f"{NAME}6-{i}", "pon_path": p, "status": "online", "rx_dbm": -20.0} for i, p in enumerate(("0/1/0", "0/1/1"))]
    _push(client, inv, "a1", NAME + "6", ok, _now(-30), pons=("0/1/0", "0/1/1"))
    onu = next(o for o in client.get(f"/v1/onus?serial={NAME}6-1", headers=h).json())
    d = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "onu_id": onu["id"]}).json()
    assert len(d["findings"]) == 1 and d["findings"][0]["evidence"]["pon_path"] == "0/1/1"   # only that ONU's PON, not the whole OLT
    assert d["scope"]["onu_id"] == onu["id"] and d["scope"]["pon_id"]
    r = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "onu_id": onu["id"], "olt_id": onu["olt_id"]})
    assert r.status_code == 422                                                                     # scopes do not mix
    assert client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D001", "onu_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    _on(migrated, seed["B"])
    assert client.post("/v1/diagnostics/runs", headers=hdr(client, "bob", seed, "B"),
                       json={"rule_id": "R-D001", "onu_id": onu["id"]}).status_code == 404         # RLS: B cannot probe A's ONU
