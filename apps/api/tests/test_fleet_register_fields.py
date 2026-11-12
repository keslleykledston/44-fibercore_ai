"""Fleet Manager registration fields (ADR-0041 amendment to D3, migration 0048): POP created while typing, management address (masked for readers), SNMP version."""
import json

import pytest
from sqlalchemy import text

from app.core import fleet
from tests.conftest import hdr

FEATURE = "fleet_manager"


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'fleet_manager'"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'FLT-%'"))
        c.execute(text("DELETE FROM pops WHERE name ILIKE 'POP-T%'"))


def _on(migrated, tenant):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,true) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = true"), {"t": tenant, "f": FEATURE})


def _body(inv, **kw):
    return {"name": "FLT-R-1", "edge_id": str(inv["a1"]["edge"]), "vendor": "huawei", **kw}


def test_address_rules_and_masking_are_pure():
    for ok in ("10.20.30.40", "100.64.9.205", "2804:7ef4:803:9587::1"):
        assert fleet.address_problem(ok) is None, ok
    for bad in ("olt.example.com", "10.0.0.1:22", "10.0.0.0/24", "999.1.1.1", "0.0.0.0", "127.0.0.1",  # noqa: S104 (refused inputs, not a bind)
                "224.0.0.1", "169.254.1.1", "::1", "", "10.0.0"):
        assert fleet.address_problem(bad) is not None, bad
    assert fleet.mask_address("10.20.30.40") == "10.20.•.•"
    assert fleet.mask_address("2804:7ef4:803:9587::1").startswith("2804:") and "9587" not in fleet.mask_address("2804:7ef4:803:9587::1")
    assert fleet.mask_address(None) is None and fleet.mask_address("") is None


def test_a_typed_site_is_found_or_created_in_the_same_request(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    r1 = client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-R-1", pop_name="  POP-T Novo Site "))
    assert r1.status_code == 201, r1.text
    pop = r1.json()["pop"]
    assert pop and pop["name"] == "POP-T Novo Site"                                              # trimmed, and the site now exists
    r2 = client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-R-2", pop_name="pop-t NOVO site"))
    assert r2.status_code == 201 and r2.json()["pop"]["id"] == pop["id"]                         # same name ignoring case: reused, not duplicated
    pops = [x for x in client.get("/v1/pops", headers=h).json()["items"] if x["name"].lower() == "pop-t novo site"]
    assert len(pops) == 1 and pops[0]["olts"] == 2
    with migrated.begin() as c:
        acts = [r[0] for r in c.execute(text("SELECT action FROM audit_log WHERE action = 'fleet.pop.created' AND evidence_redacted->>'name' = 'POP-T Novo Site'")).all()]
    assert acts == ["fleet.pop.created"]                                                          # created once, audited once
    # both ids and a name at once is ambiguous
    assert client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-R-3", pop_id=pop["id"], pop_name="POP-T Outro")).status_code == 422


def test_a_refused_olt_leaves_no_stray_site_behind(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    assert client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-R-1")).status_code == 201
    dup = client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-R-1", pop_name="POP-T Fantasma"))
    assert dup.status_code == 409
    bad = client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-R-9", pop_name="POP-T Fantasma2", edge_id="00000000-0000-0000-0000-000000000001"))
    assert bad.status_code == 404
    names = [x["name"] for x in client.get("/v1/pops", headers=h).json()["items"]]
    assert "POP-T Fantasma" not in names and "POP-T Fantasma2" not in names


def test_editing_an_olt_can_also_file_it_under_a_typed_site(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    o = client.post("/v1/fleet/olts", headers=h, json=_body(inv)).json()
    r = client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"pop_name": "POP-T Pelo Patch"})
    assert r.status_code == 200 and r.json()["pop"]["name"] == "POP-T Pelo Patch"
    assert client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"pop_name": None}).status_code == 422   # nothing to change
    assert client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"pop_id": None}).json()["pop"] is None


def test_the_management_address_is_stored_but_only_returned_masked(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    r = client.post("/v1/fleet/olts", headers=h, json=_body(inv, mgmt_address=" 10.20.30.40 ", snmp_version="v2c"))
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["mgmt_address_masked"] == "10.20.•.•" and o["snmp_version"] == "v2c"
    blob = json.dumps([o, client.get(f"/v1/fleet/olts/{o['id']}", headers=h).json(), client.get("/v1/fleet/olts", headers=h).json()])
    assert "10.20.30.40" not in blob and "30.40" not in blob and "mgmt_address\"" not in blob      # no response ever carries the full address
    with migrated.begin() as c:
        stored = c.execute(text("SELECT host(mgmt_address) FROM olts WHERE name = 'FLT-R-1'")).scalar_one()
        audits = json.dumps([r[0] for r in c.execute(text("SELECT evidence_redacted FROM audit_log WHERE target_id = :i"), {"i": o["id"]}).all()])
    assert stored == "10.20.30.40"
    assert "10.20.30.40" not in audits and '"has_mgmt_address": true' in audits                   # audit says that one is set, never which
    # replace, then clear with an explicit null
    p1 = client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"mgmt_address": "10.99.1.2", "snmp_version": "v3"})
    assert p1.status_code == 200 and p1.json()["mgmt_address_masked"] == "10.99.•.•" and p1.json()["snmp_version"] == "v3" and "10.99.1.2" not in p1.text
    with migrated.begin() as c:
        audits2 = json.dumps([r[0] for r in c.execute(text("SELECT evidence_redacted FROM audit_log WHERE target_id = :i"), {"i": o["id"]}).all()])
    assert "10.99.1.2" not in audits2
    p2 = client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"mgmt_address": None, "snmp_version": None})
    assert p2.json()["mgmt_address_masked"] is None and p2.json()["snmp_version"] is None
    # untouched fields stay when only one is sent
    p3 = client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"mgmt_address": "2804:7ef4:803:9587::1"})
    assert p3.json()["mgmt_address_masked"].startswith("2804:") and "9587" not in p3.text


def test_bad_addresses_and_versions_are_refused_without_echo(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    for bad in ("olt.example.com", "10.0.0.1:22", "10.0.0.0/24", "127.0.0.1", "0.0.0.0", "999.9.9.9"):  # noqa: S104 (refused inputs, not a bind)
        r = client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-BAD", mgmt_address=bad))
        assert r.status_code == 422, bad
    for bad in ("v1", "V3", "snmpv3", ""):
        assert client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-BAD", snmp_version=bad)).status_code == 422, bad
    # login / password / community have no field here: they are refused, not stored (D3 unchanged for secrets)
    for k in ("password", "login", "username", "snmp_community", "community", "secret"):
        assert client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-BAD", **{k: "x"})).status_code == 422, k
    assert [x for x in client.get("/v1/fleet/olts", headers=h).json()["items"] if x["name"] == "FLT-BAD"] == []


def test_the_database_keeps_the_address_a_single_host(migrated, seed, inv):
    from sqlalchemy.exc import DBAPIError
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level) VALUES (:t,:e,'FLT-DB','huawei','identified')"), {"t": seed["A"], "e": inv["a1"]["edge"]})
    for sql in ("UPDATE olts SET mgmt_address = '10.0.0.0/24' WHERE name = 'FLT-DB'", "UPDATE olts SET snmp_version = 'v1' WHERE name = 'FLT-DB'"):
        with pytest.raises(DBAPIError):
            with migrated.begin() as c:
                c.execute(text(sql))
