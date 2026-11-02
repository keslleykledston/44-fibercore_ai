"""ONU discovery queue (FC25-01/02/03): serials waiting for authorisation, READ-ONLY. Only the Edge's read is authoritative; nothing here authorises, opens a job or writes to equipment."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import agent, hdr, snap

FEATURE = "onu_discovery"


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'onu_discovery'"))
        c.execute(text("DELETE FROM onu_discovery_observations"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-DS-%'"))


def _on(migrated, tenant, value=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,:v) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = :v"),
                  {"t": tenant, "f": FEATURE, "v": value})


def _olt(client, inv, h, name, key="a1", **kw):
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, key), json=snap(inv, key, name=name, **kw))
    assert r.status_code == 202, r.text
    return next(o["id"] for o in client.get("/v1/olts?limit=1000", headers=h).json() if o["name"] == name)


def _item(serial="DSTC00000001", pon="0/1/3", when=None, **kw):
    return {"pon_path": pon, "serial": serial, "observed_at": (when or datetime.now(UTC)).isoformat(), **kw}


def _post(client, h, olt, items, source="fixture"):
    return client.post(f"/v1/olts/{olt}/onus/unregistered/import", headers=h, json={"source": source, "items": items})


def _row(client, h, olt, serial):
    return next(i for i in client.get(f"/v1/olts/{olt}/onus/unregistered", headers=h).json()["items"] if i["serial"] == serial)


def test_off_by_default_and_needs_the_permission(client, seed, inv, migrated):
    h, hn1 = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")
    olt = _olt(client, inv, h, "OLT-DS-OFF")
    r = _post(client, h, olt, [_item()])
    assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
    assert client.get("/v1/discovery/onus", headers=h).status_code == 403
    _on(migrated, seed["A"])
    assert client.get("/v1/discovery/onus", headers=h).status_code == 200
    assert client.get("/v1/discovery/onus", headers=hn1).status_code == 403               # noc_n1 holds no discovery permission
    assert _post(client, hn1, olt, [_item()]).status_code == 403


def test_import_is_idempotent_and_validates_what_it_stores(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-DS-1")
    r = _post(client, h, olt, [_item(vendor_hint="huawei"), _item(serial="dstc00000002")])
    assert r.status_code == 201 and (r.json()["created"], r.json()["updated"]) == (2, 0), r.text
    again = _post(client, h, olt, [_item(), _item(serial="DSTC00000002")]).json()
    assert (again["created"], again["updated"]) == (0, 2)
    row = _row(client, h, olt, "DSTC00000002")                                               # serial normalised to upper case
    assert row["seen_count"] == 2 and row["authorization"] == "not_available" and row["erp_association"] == "unavailable" and row["customer"] is None
    now = datetime.now(UTC)
    bad = [[{**_item(), "observed_at": (now + timedelta(hours=1)).isoformat()}], [{**_item(), "observed_at": "2026-01-01T00:00:00"}], [_item(pon="not-a-pon")],
           [_item(serial="x")], [_item(), _item()], [{**_item(), "evil": 1}], []]
    for items in bad:
        assert _post(client, h, olt, items).status_code == 422, items
    assert client.post(f"/v1/olts/{olt}/onus/unregistered/import", headers=h, json={"source": "edge_read", "items": [_item()]}).status_code == 422   # reserved for the Edge reader


def test_conditions_new_waiting_stale_and_conflict(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    a, b = _olt(client, inv, h, "OLT-DS-A"), _olt(client, inv, h, "OLT-DS-B")
    now = datetime.now(UTC)
    assert _post(client, h, a, [_item("DSNEW0000001"), _item("DSOLD0000001", when=now - timedelta(hours=30)), _item("DSSTALE00001", when=now - timedelta(hours=2)),
                                 _item("HWTC00000001"), _item("DSDUP0000001")]).status_code == 201   # HWTC00000001 is already a registered ONU in this tenant
    assert _post(client, h, b, [_item("DSDUP0000001", pon="0/2/0")]).status_code == 201              # the same serial at ANOTHER OLT/PON
    with migrated.begin() as c:                                                                      # DSOLD: first seen 30 h ago, seen again just now
        c.execute(text("UPDATE onu_discovery_observations SET last_seen_at = now() WHERE serial = 'DSOLD0000001'"))
    assert _row(client, h, a, "DSNEW0000001")["condition"] == "new"
    assert _row(client, h, a, "DSOLD0000001")["condition"] == "waiting"
    st = _row(client, h, a, "DSSTALE00001")
    assert st["condition"] == "stale" and st["reasons"] == ["not_seen_recently"]
    reg = _row(client, h, a, "HWTC00000001")
    assert reg["condition"] == "conflict" and reg["reasons"] == ["already_registered"]
    dup = _row(client, h, a, "DSDUP0000001")
    assert dup["condition"] == "conflict" and dup["reasons"] == ["seen_elsewhere"] and _row(client, h, b, "DSDUP0000001")["condition"] == "conflict"
    only = client.get("/v1/discovery/onus?condition=conflict", headers=h).json()["items"]
    assert {i["serial"] for i in only} == {"HWTC00000001", "DSDUP0000001"}
    assert client.get("/v1/discovery/onus?condition=nonsense", headers=h).status_code == 422


def test_a_manual_import_never_refreshes_what_the_olt_said(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-DS-AUTH")
    old = datetime.now(UTC) - timedelta(hours=3)
    assert _post(client, h, olt, [_item("DSAUTH000001", when=old)]).status_code == 201
    with migrated.begin() as c:                                                                      # stand-in for the supervised Edge reader (not delivered yet)
        c.execute(text("UPDATE onu_discovery_observations SET source = 'edge_read' WHERE serial = 'DSAUTH000001'"))
    assert _post(client, h, olt, [_item("DSAUTH000001")], source="manual_import").status_code == 201   # a person says "I saw it just now"
    row = _row(client, h, olt, "DSAUTH000001")
    assert row["authoritative"] is True and row["source"] == "edge_read" and row["condition"] == "stale"   # the OLT's own (old) sighting wins and is NOT refreshed
    assert _post(client, h, olt, [_item("DSNOAUTH0001")], source="manual_import").status_code == 201
    assert _row(client, h, olt, "DSNOAUTH0001")["authoritative"] is False


def test_tenant_isolation_and_nothing_else_is_created(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    _on(migrated, seed["B"])
    ha, hb = hdr(client, "alice", seed, "A"), hdr(client, "bob", seed, "B")
    olt = _olt(client, inv, ha, "OLT-DS-ISO")
    with migrated.begin() as cn:
        before = cn.execute(text("SELECT (SELECT count(*) FROM jobs), (SELECT count(*) FROM events_outbox), (SELECT count(*) FROM incidents)")).one()
    assert _post(client, ha, olt, [_item("DSISO0000001")]).status_code == 201
    assert client.get("/v1/discovery/onus", headers=hb).json()["items"] == []
    assert client.get(f"/v1/olts/{olt}/onus/unregistered", headers=hb).status_code == 404         # another tenant's OLT does not exist for B
    assert _post(client, hb, olt, [_item("DSISO0000001")]).status_code == 404
    with migrated.begin() as cn:
        after = cn.execute(text("SELECT (SELECT count(*) FROM jobs), (SELECT count(*) FROM events_outbox), (SELECT count(*) FROM incidents)")).one()
    assert after == before                                                                          # no job, no event, no incident


def test_the_table_is_append_only_for_the_app_role(client, seed, inv, migrated):
    from app.core.db import get_engine, scoped_connection
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-DS-IMM")
    assert _post(client, h, olt, [_item("DSIMM0000001")]).status_code == 201
    for stmt in ("DELETE FROM onu_discovery_observations", "UPDATE onu_discovery_observations SET serial = 'ZZZZ0000'", "UPDATE onu_discovery_observations SET source = 'edge_read'"):
        with pytest.raises(DBAPIError), scoped_connection(get_engine(), tenant_id=seed["A"]) as c:
            c.execute(text(stmt))
    with migrated.begin() as c:
        assert tuple(c.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'onu_discovery_observations'")).one()) == (True, True)


def test_the_filter_is_applied_before_paging_so_a_page_never_hides_a_match(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    a, b = _olt(client, inv, h, "OLT-DS-P1"), _olt(client, inv, h, "OLT-DS-P2")
    assert _post(client, h, a, [_item(f"DSPAGE{i:06d}", pon="0/1/1") for i in range(5)]).status_code == 201
    assert _post(client, h, b, [_item("HWTC00000001", pon="0/9/9")]).status_code == 201         # the only conflict, on the LAST OLT in the scan order
    first = client.get("/v1/discovery/onus?limit=2", headers=h).json()
    assert len(first["items"]) == 2 and first["total"] >= 6 and first["truncated"] is True and first["scan_capped"] is False
    conflicts = client.get("/v1/discovery/onus?condition=conflict&limit=2", headers=h).json()
    assert [i["serial"] for i in conflicts["items"]] == ["HWTC00000001"] and conflicts["total"] == 1 and conflicts["truncated"] is False
    seen: list[str] = []
    for off in range(0, first["total"], 2):                                                         # paging walks every row exactly once
        seen += [i["id"] for i in client.get(f"/v1/discovery/onus?limit=2&offset={off}", headers=h).json()["items"]]
    assert len(seen) == len(set(seen)) == first["total"]
    assert client.get("/v1/discovery/onus?limit=0", headers=h).status_code == 422 and client.get("/v1/discovery/onus?limit=501", headers=h).status_code == 422
