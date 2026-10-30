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
        c.execute(text("DELETE FROM onu_cpe_links WHERE cpe_id IN (SELECT id FROM cpes WHERE canonical_serial LIKE 'DGC%')"))
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'DGC%'"))  # cpe_state and bindings follow (ON DELETE CASCADE)
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
    assert [(x["id"], x["version"], x["read_only"]) for x in rules] == [("R-D001", 1, True), ("R-D002", 1, True)]
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


# ---- R-D002 v1: the WAN as the CPE reports it (pure) ----------------------------------------------------------------------------------
def _c(state, fresh=True):
    return {"state": state, "fresh": fresh}


def _cpe_row(**kw):
    base = {"subject_id": "c1", "wan_link": "Up", "wan_link_fresh": True, "connections": [_c("Disconnected")], "newest_age_seconds": 60,
            "oldest_age_seconds": 60, "onu_link": "none", "onu_status": None, "onu_fresh": False}
    base.update(kw)
    return base


def _verdict(**kw):
    rule = diagnostics.RULES[("R-D002", 1)]
    return diagnostics.run(rule, [_cpe_row(**kw)])[0]


def test_r_d002_never_claims_without_a_fresh_observation():
    none = _verdict(wan_link=None, wan_link_fresh=False, connections=[], newest_age_seconds=None, oldest_age_seconds=None)
    assert none["status"] == "unknown" and "no WAN observation" in none["reason"] and none["requires_human_confirmation"] is False
    old = _verdict(connections=[_c("Disconnected", False)], newest_age_seconds=99999, oldest_age_seconds=99999)
    assert old["status"] == "unknown" and "too long ago" in old["reason"] and old["hypothesis"] is None
    assert old["evidence"]["oldest_age_seconds"] == 99999  # the evidence shows how old, not a made-up value
    only_old_link = _verdict(wan_link="Down", wan_link_fresh=False, connections=[])
    assert only_old_link["status"] == "unknown" and "too old" in only_old_link["reason"]


def test_r_d002_one_recent_reading_never_vouches_for_an_old_one():
    # a recent Disconnected next to an OLD reading of another connection: that one could still be established -> no claim
    mixed = _verdict(connections=[_c("Disconnected", True), _c("Disconnected", False)], newest_age_seconds=10, oldest_age_seconds=90000)
    assert mixed["status"] == "unknown" and "rule out that it is established" in mixed["reason"] and mixed["hypothesis"] is None
    # ...and an old Disconnected next to a recent Connected is simply the recent Connected
    assert _verdict(connections=[_c("Connected", True), _c("Disconnected", False)])["status"] == "observed"
    # an OLD Connected never counts as established
    assert _verdict(connections=[_c("Connected", False), _c("Disconnected", True)])["status"] == "unknown"


def test_r_d002_down_needs_every_reported_connection_down_and_is_only_a_hypothesis():
    sess = _verdict(connections=[_c("Disconnected")])
    assert sess["status"] == "inferred" and sess["suspected_cause"] == "wan_session_down" and sess["requires_human_confirmation"] is True
    assert _verdict(connections=[_c("Disconnected"), _c("Error")], wan_link="Down")["suspected_cause"] == "wan_link_down"
    # a link that was not read, or read too long ago, is not a claim about the link
    assert _verdict(connections=[_c("Down")], wan_link=None, wan_link_fresh=False)["suspected_cause"] == "wan_connection_down"
    assert _verdict(connections=[_c("Down")], wan_link="Up", wan_link_fresh=False)["suspected_cause"] == "wan_connection_down"
    assert _verdict(connections=[_c("Down")], wan_link="Down", wan_link_fresh=False)["suspected_cause"] == "wan_connection_down"
    for link in ("Initializing", "Unavailable"):  # a recent link reading that is neither Up nor Down says nothing about the session
        v = _verdict(connections=[_c("Disconnected")], wan_link=link)
        assert v["status"] == "inferred" and v["suspected_cause"] == "wan_connection_down" and "session" not in v["hypothesis"], link
    # anything established wins; transitional/unknown states never become a claim
    assert _verdict(connections=[_c("Connected"), _c("Disconnected")])["status"] == "observed"
    assert _verdict(connections=[_c("Up")])["status"] == "observed"
    for state in ("Connecting", "PendingDisconnect", "Disconnecting", "Dormant", "Unknown"):
        v = _verdict(connections=[_c(state)])
        assert v["status"] == "observed" and v["hypothesis"] is None and "not conclusive" in v["reason"], state
    assert _verdict(connections=[_c("Disconnected"), _c("Connecting")])["status"] == "observed"  # one transitional state keeps it inconclusive
    only_link = _verdict(connections=[], wan_link="Down")  # only a recent link reading: not enough for a connection claim
    assert only_link["status"] == "observed" and "only the WAN link" in only_link["reason"]


def test_r_d002_onu_only_adds_context_and_never_changes_the_verdict():
    base = _verdict(connections=[_c("Disconnected")])
    up = _verdict(connections=[_c("Disconnected")], onu_link="confirmed", onu_status="online", onu_fresh=True)
    down = _verdict(connections=[_c("Disconnected")], onu_link="confirmed", onu_status="los", onu_fresh=True)
    stale = _verdict(connections=[_c("Disconnected")], onu_link="confirmed", onu_status="online", onu_fresh=False)
    assert {base["status"], up["status"], down["status"], stale["status"]} == {"inferred"}
    assert {base["suspected_cause"], up["suspected_cause"], down["suspected_cause"], stale["suspected_cause"]} == {"wan_session_down"}
    assert "access layer is up" in up["context"] and "can be a consequence" in down["context"]
    assert "not considered" in base["context"] and "not considered" in stale["context"]


def test_r_d002_is_registered_deterministic_and_replays():
    assert diagnostics.latest("R-D002").version == 1 and diagnostics.RULES[("R-D002", 1)].subject == "cpe"
    rows = [_cpe_row(subject_id="a"), _cpe_row(subject_id="b", connections=[_c("Connected")])]
    rule = diagnostics.RULES[("R-D002", 1)]
    a, b = diagnostics.run(rule, rows), diagnostics.run(rule, rows)
    assert a == b and json.loads(json.dumps(a)) == a and a[0]["evidence_refs"] == [{"type": "cpe", "id": "a"}]
    assert [f["finding_id"] for f in a] == ["R-D002/v1/a", "R-D002/v1/b"]
    rnd = random.Random(7)  # noqa: S311  property: the verdict depends only on the inputs and never claims on old or absent readings
    states = ["Connected", "Up", "Disconnected", "Down", "Connecting", "Unknown", "Error", "Dormant", "NotPresent"]
    for _ in range(800):
        conns = sorted((_c(st, rnd.random() < 0.7) for st in rnd.sample(states, rnd.randint(0, 3))), key=lambda c: (c["state"], c["fresh"]))
        row = _cpe_row(connections=conns, wan_link=rnd.choice([None, "Up", "Down"]), wan_link_fresh=rnd.random() < 0.7,
                       onu_link=rnd.choice(["none", "confirmed"]), onu_status=rnd.choice([None, "online", "los"]), onu_fresh=rnd.random() < 0.5)
        f = diagnostics.run(rule, [row])[0]
        assert f == diagnostics.run(rule, [dict(row)])[0]
        if f["status"] == "inferred":  # a claim needs readings that are ALL recent and NONE established
            assert row["connections"] and all(c["fresh"] for c in row["connections"])
            assert not {c["state"] for c in row["connections"]} & {"Connected", "Up"}
        if not row["connections"] and row["wan_link"] is None:
            assert f["status"] == "unknown"


# ---- R-D002 through the API ------------------------------------------------------------------------------------------------------------
def _cpe_with_state(client, inv, migrated, seed, serial, ext, metrics, onu_status=None):
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": serial, "vendor": "ACME", "model": "G3000", "binding": {"protocol": "tr069", "external_id": ext, "connector_id": "c-dg"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    if metrics:
        st = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "states": [
            {"binding": {"protocol": "tr069", "external_id": ext, "connector_id": "c-dg"}, "metrics": metrics}]}
        assert client.post("/v1/edge/cpe-state", headers=agent(client, inv, "a1"), json=st).status_code == 202
    h = hdr(client, "alice", seed, "A")
    cpe = next(c["id"] for c in client.get("/v1/cpes", headers=h).json() if c["canonical_serial"] == serial)
    onu = None
    if onu_status:
        _push(client, inv, "a1", NAME + serial, [{"serial": serial, "pon_path": "0/1/0", "status": onu_status, "rx_dbm": -20.0}], _now(-30))
        onu = client.get(f"/v1/onus?serial={serial}", headers=h).json()[0]["id"]
        with migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text("INSERT INTO onu_cpe_links (tenant_id, onu_id, cpe_id, status, confidence, evidence, reviewed_by, reviewed_at) "
                           "VALUES (:t,:o,:c,'confirmed',1,CAST('{\"rule\":\"manual\"}' AS jsonb),:u,now())"),
                      {"t": str(seed["A"]), "o": onu, "c": cpe, "u": str(seed["alice"])})
    return cpe, onu


def _m(name, scope, value, at=None):
    return {"name": name, "scope": scope, "value": value, "captured_at": at or _now(-60)}


def test_r_d002_run_reads_the_stored_state_is_read_only_and_reproducible(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    cpe, onu = _cpe_with_state(client, inv, migrated, seed, "DGC-0001", "dgc-1",
                               [_m("wan_link_status", "link/1", "Up"), _m("wan_connection_status", "ppp/3/1", "Disconnected")], onu_status="online")
    with migrated.begin() as c:
        before = c.execute(text("SELECT (SELECT count(*) FROM incidents), (SELECT count(*) FROM cpe_state), (SELECT count(*) FROM events_outbox)")).one()
    r = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D002", "cpe_id": cpe})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["scope"]["cpe_id"] == cpe and d["rule_version"] == 1 and d["truncated"] is False and len(d["findings"]) == 1
    f = d["findings"][0]
    assert f["status"] == "inferred" and f["suspected_cause"] == "wan_session_down" and f["requires_human_confirmation"] is True
    assert f["evidence"]["connections"] == [{"state": "Disconnected", "fresh": True}] and f["evidence"]["wan_link"] == "Up"
    assert f["evidence"]["wan_link_fresh"] is True and "access layer is up" in f["context"] and f["evidence"]["newest_age_seconds"] < 300
    with migrated.begin() as c:
        after = c.execute(text("SELECT (SELECT count(*) FROM incidents), (SELECT count(*) FROM cpe_state), (SELECT count(*) FROM events_outbox)")).one()
        stored = c.execute(text("SELECT inputs FROM diagnostic_runs WHERE id = :i"), {"i": d["run_id"]}).scalar_one()
    assert after == before  # a run opens no incident, writes no state and publishes no event
    assert "DGC-0001" not in json.dumps(stored) and set(stored[0]) == {
        "subject_id", "wan_link", "wan_link_fresh", "connections", "newest_age_seconds", "oldest_age_seconds", "onu_link", "onu_status",
        "onu_fresh"}  # no serial, no free text
    assert client.get(f"/v1/diagnostics/runs/{d['run_id']}", headers=h).json()["reproducible"] is True
    # the same CPE reached through its confirmed ONU
    r2 = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D002", "onu_id": onu})
    assert r2.status_code == 201 and r2.json()["scope"]["cpe_id"] == cpe and r2.json()["findings"][0]["status"] == "inferred"


def test_r_d002_old_or_missing_state_is_unknown_and_scopes_are_validated(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    old, _ = _cpe_with_state(client, inv, migrated, seed, "DGC-0002", "dgc-2", [_m("wan_connection_status", "ppp/1/1", "Disconnected", _now(-7200))])
    none, _ = _cpe_with_state(client, inv, migrated, seed, "DGC-0003", "dgc-3", [])
    for cpe, why in ((old, "too long ago"), (none, "no WAN observation")):
        f = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D002", "cpe_id": cpe}).json()["findings"][0]
        assert f["status"] == "unknown" and why in f["reason"] and f["hypothesis"] is None
    post = lambda body: client.post("/v1/diagnostics/runs", headers=h, json=body)  # noqa: E731
    assert post({"rule_id": "R-D002"}).status_code == 422                                               # a CPE rule needs a CPE
    assert post({"rule_id": "R-D002", "cpe_id": old, "olt_id": old}).status_code == 422                 # exclusive scopes
    assert post({"rule_id": "R-D002", "olt_id": old}).status_code == 422
    assert post({"rule_id": "R-D001", "cpe_id": old}).status_code == 422                                # a PON rule does not take a CPE
    assert post({"rule_id": "R-D002", "cpe_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    onu_only = _cpe_with_state(client, inv, migrated, seed, "DGC-0004", "dgc-4", [])
    assert onu_only[1] is None
    _push(client, inv, "a1", NAME + "L", [{"serial": "DGC-LONELY", "pon_path": "0/1/0", "status": "online", "rx_dbm": -20.0}], _now(-30))
    lonely = client.get("/v1/onus?serial=DGC-LONELY", headers=h).json()[0]["id"]
    assert post({"rule_id": "R-D002", "onu_id": lonely}).status_code == 409                             # no confirmed link: nothing to read


def test_r_d002_is_tenant_isolated(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    _on(migrated, seed["B"])
    cpe, _ = _cpe_with_state(client, inv, migrated, seed, "DGC-0005", "dgc-5", [_m("wan_connection_status", "ppp/1/1", "Disconnected")])
    assert client.post("/v1/diagnostics/runs", headers=hdr(client, "bob", seed, "B"), json={"rule_id": "R-D002", "cpe_id": cpe}).status_code == 404


def test_r_d002_a_recent_reading_of_one_connection_does_not_refresh_an_old_one(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    cpe, _ = _cpe_with_state(client, inv, migrated, seed, "DGC-0006", "dgc-6", [
        _m("wan_connection_status", "ppp/1/1", "Disconnected", _now(-7200)), _m("wan_connection_status", "ip/2/1", "Disconnected", _now(-30))])
    f = client.post("/v1/diagnostics/runs", headers=h, json={"rule_id": "R-D002", "cpe_id": cpe}).json()["findings"][0]
    assert f["status"] == "unknown" and f["hypothesis"] is None and "rule out that it is established" in f["reason"]
    assert sorted((c["state"], c["fresh"]) for c in f["evidence"]["connections"]) == [("Disconnected", False), ("Disconnected", True)]
    assert f["evidence"]["oldest_age_seconds"] >= 7200 and f["evidence"]["newest_age_seconds"] < 300
