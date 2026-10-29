"""NOC Command Center (FC22-009): impact (distinct customers via APPROVED associations, with its source), the documented priority order,
the header summary and the incident detail for the drawer."""
import json

import pytest
from sqlalchemy import event, text

from tests.conftest import _now, agent, hdr, snap

PFX = "NCC"


@pytest.fixture(autouse=True)
def _cleanup(migrated, inv):
    with migrated.begin() as c:   # other modules leave stale heartbeats on the shared edges: start every test with healthy ones
        c.execute(text("UPDATE edges SET last_heartbeat_at = now() WHERE id = ANY(:e)"), {"e": [inv["a1"]["edge"], inv["a2"]["edge"]]})
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM associations WHERE customer_id IN (SELECT id FROM customers WHERE erp_source = 'ncctest')"))
        c.execute(text("DELETE FROM customers WHERE erp_source = 'ncctest'"))
        c.execute(text("DELETE FROM incident_onus WHERE onu_id IN (SELECT id FROM onus WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-NCC-%'))"))
        c.execute(text("DELETE FROM incidents WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-NCC-%')"))
        c.execute(text("DELETE FROM onus WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-NCC-%')"))
        c.execute(text("DELETE FROM pon_ports WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-NCC-%')"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-NCC-%'"))
        c.execute(text("DELETE FROM tenant_memberships WHERE role = 'support'"))


def _outage(client, inv, name, n=10, key="a1", down=None):
    """n ONUs online, then `down` of them drop (los) together: a PON event."""
    down = n if down is None else down
    ok = [{"serial": f"{name}-{i:02d}", "pon_path": "0/1/0", "status": "online", "rx_dbm": -20.0} for i in range(n)]
    bad = [{**o, "status": "los", "rx_dbm": None} if i < down else o for i, o in enumerate(ok)]
    pons = [{"pon_path": "0/1/0", "status": "up", "complete": True}]
    for items, when in ((ok, -600), (bad, -540)):
        r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, key), json=snap(inv, key, name=name, observed=_now(when), onus=items, pons=pons))
        assert r.status_code == 202, r.text


def _mine(client, h, name, **q):
    return [i for i in client.get("/v1/incidents", headers=h, params=q).json()["incidents"] if i["olt"] == name]


def _approve(migrated, tenant, reviewer, serial, customer_label, status="approved"):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        cid = c.execute(text("SELECT id FROM customers WHERE erp_source = 'ncctest' AND erp_customer_id = :e"), {"e": customer_label}).scalar()
        if cid is None:
            cid = c.execute(text("INSERT INTO customers(tenant_id, erp_source, erp_customer_id, display_name) VALUES (:t,'ncctest',:e,'Cliente NCC') "
                                 "RETURNING id"), {"t": tenant, "e": customer_label}).scalar()
        onu = c.execute(text("SELECT id FROM onus WHERE serial = :s"), {"s": serial}).scalar()
        c.execute(text("INSERT INTO associations(tenant_id, onu_id, customer_id, status, score, evidence, reviewed_by, reviewed_at) "
                       "VALUES (:t,:o,:c,:s,100,CAST('{}' AS jsonb),:r,CASE WHEN :s = 'suggested' THEN NULL ELSE now() END)"),
                  {"t": tenant, "o": onu, "c": cid, "s": status, "r": reviewer if status != "suggested" else None})


def test_impact_counts_distinct_customers_through_approved_associations_only(client, seed, inv, migrated):
    h = hdr(client, "alice", seed, "A")
    _outage(client, inv, "OLT-NCC-1")
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-1-00", "c1")
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-1-01", "c1")                       # same customer, second ONU: counts once
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-1-02", "c2")
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-1-03", "c3", status="suggested")   # only suggested: nobody confirmed it
    inc = _mine(client, h, "OLT-NCC-1")
    assert len(inc) == 1
    assert inc[0]["impact"] == {"customers_affected": 2, "source": "associations_approved", "hidden": False, "members_known": True}


def test_impact_is_hidden_not_zero_without_customers_read_and_unknown_without_members(client, seed, inv, migrated):
    ha, hd = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")     # dave = noc_n1: incidents yes, customers no
    _outage(client, inv, "OLT-NCC-2")
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-2-00", "c1")
    hidden = _mine(client, hd, "OLT-NCC-2")[0]["impact"]
    assert hidden == {"customers_affected": None, "source": "associations_approved", "hidden": True, "members_known": True}
    s = client.get("/v1/incidents", headers=hd).json()["summary"]
    assert s["customers_affected"] is None and s["customers_hidden"] is True
    with migrated.begin() as c:   # an incident opened before membership existed: impact UNKNOWN, never 0
        c.execute(text("DELETE FROM incident_onus WHERE onu_id IN (SELECT id FROM onus WHERE serial LIKE 'OLT-NCC-2-%')"))
    legacy = _mine(client, ha, "OLT-NCC-2")[0]["impact"]
    assert legacy["customers_affected"] is None and legacy["members_known"] is False and legacy["hidden"] is False


def test_priority_order_is_the_documented_one(client, seed, inv, migrated):
    h = hdr(client, "alice", seed, "A")
    _outage(client, inv, "OLT-NCC-3", n=10)               # big
    _outage(client, inv, "OLT-NCC-4", n=6)                # smaller
    _outage(client, inv, "OLT-NCC-5", n=8)                # will be acknowledged
    for k in range(4):
        _approve(migrated, seed["A"], seed["alice"], f"OLT-NCC-4-{k:02d}", f"p{k}")     # 4 customers on the SMALLER outage
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-3-00", "q0")                   # 1 customer on the bigger one
    for k in range(6):
        _approve(migrated, seed["A"], seed["alice"], f"OLT-NCC-5-{k:02d}", f"r{k}")     # the ACKNOWLEDGED one has the largest impact (6)
    ack = _mine(client, h, "OLT-NCC-5")[0]["id"]
    assert client.post(f"/v1/incidents/{ack}/ack", headers=h).status_code == 200
    mine = ["OLT-NCC-3", "OLT-NCC-4", "OLT-NCC-5"]
    ordered = [i["olt"] for i in client.get("/v1/incidents", headers=h, params={"order": "priority", "limit": 500}).json()["incidents"] if i["olt"] in mine]
    assert ordered == ["OLT-NCC-4", "OLT-NCC-3", "OLT-NCC-5"]   # impact beats raw size; acknowledged goes after the unacknowledged ones
    #                                                             ^ even though NCC-5 reaches the most customers (6): unacknowledged work comes first
    recent = [i["olt"] for i in client.get("/v1/incidents", headers=h, params={"limit": 500}).json()["incidents"] if i["olt"] in mine]
    assert recent == ["OLT-NCC-5", "OLT-NCC-4", "OLT-NCC-3"]    # the default order is unchanged (most recent first)
    assert client.get("/v1/incidents", headers=h, params={"order": "bogus"}).status_code == 422


def test_unknown_impact_sorts_after_known_impact(client, seed, inv, migrated):
    hd = hdr(client, "dave", seed, "A")
    _outage(client, inv, "OLT-NCC-6", n=10)
    _outage(client, inv, "OLT-NCC-7", n=6)
    ordered = [i["olt"] for i in client.get("/v1/incidents", headers=hd, params={"order": "priority", "limit": 500}).json()["incidents"]
               if i["olt"] in ("OLT-NCC-6", "OLT-NCC-7")]
    assert ordered == ["OLT-NCC-6", "OLT-NCC-7"]   # nobody sees customers: falls back to ONUs down, never to a fabricated 0 vs 0 tie-break


def test_summary_is_over_all_open_incidents_and_distinct_across_them(client, seed, inv, migrated):
    h = hdr(client, "alice", seed, "A")
    before = client.get("/v1/incidents", headers=h).json()["summary"]
    _outage(client, inv, "OLT-NCC-8", n=8)
    _outage(client, inv, "OLT-NCC-9", n=8)
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-8-00", "shared")
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-9-00", "shared")      # the same customer affected by two incidents
    after = client.get("/v1/incidents", headers=h, params={"limit": 1}).json()["summary"]  # a tiny page must not shrink the totals
    assert after["open"] == before["open"] + 2 and after["unacknowledged"] == before["unacknowledged"] + 2
    assert after["customers_affected"] == before["customers_affected"] + 1       # distinct, not 2
    assert set(after) == {"open", "unacknowledged", "silent_edges", "open_suppressed", "customers_affected", "customers_source",
                          "customers_hidden"}   # the header shows 4 numbers; `open_suppressed` only qualifies the open count


def test_impact_is_one_query_for_all_incidents(client, seed, inv, migrated):
    from app.core.db import get_engine
    h = hdr(client, "alice", seed, "A")
    for k in range(3):
        _outage(client, inv, f"OLT-NCC-Q{k}", n=6)
    seen: list[str] = []

    def spy(conn, cursor, statement, *rest):
        seen.append(statement)
    eng = get_engine()
    event.listen(eng, "before_cursor_execute", spy)
    try:
        assert client.get("/v1/incidents", headers=h).status_code == 200
    finally:
        event.remove(eng, "before_cursor_execute", spy)
    assert sum("incident_onus" in s and "associations" in s and "unnest" in s for s in seen) == 1   # no per-incident query


def test_incident_detail_for_the_drawer(client, seed, inv, migrated, monkeypatch):
    from app.api import noc
    ha, hd, hb = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A"), hdr(client, "bob", seed, "B")
    _outage(client, inv, "OLT-NCC-D", n=10)
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-D-00", "d1")
    iid = _mine(client, ha, "OLT-NCC-D")[0]["id"]
    d = client.get(f"/v1/incidents/{iid}", headers=ha).json()
    assert d["olt"] == "OLT-NCC-D" and d["status"] == "open" and d["members_total"] == 10 and d["members_truncated"] is False
    assert d["impact"]["customers_affected"] == 1 and d["evidence"]["onus_down"] == 10
    assert [m["serial"] for m in d["members"]] == sorted(m["serial"] for m in d["members"])
    blob = json.dumps(d)
    assert "Cliente NCC" not in blob and "customer" not in {k for m in d["members"] for k in m}   # inventory only: no customer names
    assert client.get(f"/v1/incidents/{iid}", headers=hd).json()["impact"]["hidden"] is True      # noc_n1 sees the incident, not the customers
    assert client.get(f"/v1/incidents/{iid}", headers=hb).status_code == 404                      # RLS: another tenant
    assert client.get("/v1/incidents/00000000-0000-0000-0000-000000000000", headers=ha).status_code == 404
    assert client.get("/v1/incidents/not-a-uuid", headers=ha).status_code == 422
    assert client.get(f"/v1/incidents/{iid}").status_code == 401
    monkeypatch.setattr(noc, "MEMBERS_SHOWN", 3)
    t = client.get(f"/v1/incidents/{iid}", headers=ha).json()
    assert len(t["members"]) == 3 and t["members_total"] == 10 and t["members_truncated"] is True   # says when it cut


def test_an_incident_behind_a_silent_edge_goes_after_a_confirmed_drop_even_with_bigger_impact(client, seed, inv, migrated):
    h = hdr(client, "alice", seed, "A")
    _outage(client, inv, "OLT-NCC-S1", n=8, key="a2")           # behind edge a2 (will go silent), BIG impact
    _outage(client, inv, "OLT-NCC-S2", n=6, key="a1")           # behind a healthy edge, small impact
    for k in range(5):
        _approve(migrated, seed["A"], seed["alice"], f"OLT-NCC-S1-{k:02d}", f"s{k}")
    _approve(migrated, seed["A"], seed["alice"], "OLT-NCC-S2-00", "t0")
    before = client.get("/v1/incidents", headers=h).json()["summary"]
    with migrated.begin() as c:
        c.execute(text("UPDATE edges SET last_heartbeat_at = now() - interval '1 day' WHERE id = :e"), {"e": inv["a2"]["edge"]})
    try:
        d = client.get("/v1/incidents", headers=h, params={"order": "priority", "limit": 500}).json()
        mine = [i for i in d["incidents"] if i["olt"] in ("OLT-NCC-S1", "OLT-NCC-S2")]
        assert [i["olt"] for i in mine] == ["OLT-NCC-S2", "OLT-NCC-S1"]          # a suppressed (last-known) event never outranks a confirmed drop
        assert mine[1]["edge_silent"] is True and mine[0]["edge_silent"] is False
        assert d["summary"]["silent_edges"] >= 1 and d["summary"]["open_suppressed"] >= 1
        # the 5 customers behind the silent edge leave the CURRENT impact (last-known state is not an outage confirmed now)
        assert d["summary"]["customers_affected"] == before["customers_affected"] - 5
        assert d["summary"]["open"] == before["open"]   # ...but the incident is still open and still listed
    finally:
        with migrated.begin() as c:
            c.execute(text("UPDATE edges SET last_heartbeat_at = now() WHERE id = :e"), {"e": inv["a2"]["edge"]})
