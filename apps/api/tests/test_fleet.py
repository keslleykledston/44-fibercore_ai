"""Fleet Manager (ADR-0041, PR2 part A): register and edit OLTs and POPs. Nothing here reaches an OLT; the credential is only a NAME (D3)."""
import json

import pytest
from sqlalchemy import text

from tests.conftest import agent, hdr, snap

FEATURE = "fleet_manager"


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'fleet_manager'"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'FLT-%'"))
        c.execute(text("DELETE FROM pops WHERE name LIKE 'POP-T%'"))


def _on(migrated, tenant, value=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,:v) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = :v"),
                  {"t": tenant, "f": FEATURE, "v": value})


def _body(inv, **kw):
    return {"name": "FLT-OLT-1", "edge_id": str(inv["a1"]["edge"]), "vendor": "huawei", **kw}


def test_off_by_default_and_roles(client, seed, inv, migrated):
    h, hn1 = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")
    assert client.get("/v1/fleet/olts", headers=h).status_code == 403 and client.get("/v1/fleet/olts", headers=h).json()["detail"] == "feature_disabled"
    assert client.post("/v1/pops", headers=h, json={"name": "POP-T0"}).status_code == 403
    _on(migrated, seed["A"])
    assert client.get("/v1/fleet/olts", headers=h).status_code == 200
    assert client.get("/v1/fleet/olts", headers=hn1).status_code == 403                  # noc_n1 holds no fleet permission
    assert client.post("/v1/fleet/olts", headers=hn1, json=_body(inv)).status_code == 403
    assert client.post("/v1/pops", headers=hn1, json={"name": "POP-T1"}).status_code == 403


def test_register_edit_and_list_without_any_secret(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    pop = client.post("/v1/pops", headers=h, json={"name": "POP-T Centro", "code": "CTR-01", "note": "sala 2"})
    assert pop.status_code == 201, pop.text
    pid = pop.json()["id"]
    r = client.post("/v1/fleet/olts", headers=h, json=_body(inv, pop_id=pid, credential_ref="olt-bva-01.ssh", label="OLT do centro"))
    assert r.status_code == 201, r.text
    o = r.json()
    assert (o["name"], o["vendor"], o["support_level"], o["registered"], o["collected"], o["onu_count"]) == ("FLT-OLT-1", "huawei", "identified", True, False, 0)
    assert o["pop"] == {"id": pid, "name": "POP-T Centro"} and o["has_credential_ref"] is True
    assert "credential_ref" not in o and "olt-bva-01.ssh" not in json.dumps(o)                 # the name of the secret is write-only: no response returns it
    assert o["model"] is None and o["firmware"] is None and o["observed_at"] is None            # nothing is claimed before the Edge reads it
    # a second one with the same name is refused, whatever the case of the first is
    assert client.post("/v1/fleet/olts", headers=h, json=_body(inv)).status_code == 409
    got = client.get("/v1/fleet/olts", headers=h).json()["items"]
    assert [x["name"] for x in got if x["name"].startswith("FLT-")] == ["FLT-OLT-1"]
    # edit: set, then clear with an explicit null
    p1 = client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"label": "Novo rótulo", "credential_ref": None})
    assert p1.status_code == 200 and p1.json()["label"] == "Novo rótulo" and p1.json()["has_credential_ref"] is False
    assert p1.json()["pop"]["id"] == pid                                                          # untouched fields stay
    p2 = client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"pop_id": None})
    assert p2.json()["pop"] is None
    assert client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={}).status_code == 422
    assert client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"name": "FLT-X"}).status_code == 422   # the name and the owning Edge are not editable here
    assert client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"edge_id": str(inv["a1"]["edge"])}).status_code == 422
    # no response carries a secret-looking key
    blob = json.dumps([client.get(f"/v1/fleet/olts/{o['id']}", headers=h).json(), client.get("/v1/fleet/olts", headers=h).json()]).lower()
    assert not any(k in blob for k in ("password", "secret", "token", "private", "olt-bva-01"))
    client.patch(f"/v1/fleet/olts/{o['id']}", headers=h, json={"credential_ref": "olt-nova-ref"})          # replace: the new name is not returned either
    assert "olt-nova-ref" not in json.dumps(client.get(f"/v1/fleet/olts/{o['id']}", headers=h).json())


def test_the_credential_is_only_a_name_never_an_address_or_a_key(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    for bad in ("10.0.0.1", "192.168.1.250", "Olt-Admin", "olt admin", "olt/admin", "http://x", "user:pass", "a" * 65, "0123456789abcdef0123456789abcdef", "-olt", ".olt", "olt;ls", ""):
        r = client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-BAD", credential_ref=bad))
        assert r.status_code == 422, bad
        assert bad.strip() == "" or bad not in r.text, "the refusal must not echo the value"
    ok = client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-OK", credential_ref="olt_ssh-01"))
    assert ok.status_code == 201
    assert client.patch(f"/v1/fleet/olts/{ok.json()['id']}", headers=h, json={"credential_ref": "10.1.2.3"}).status_code == 422
    # the database refuses it too, whatever the API does (constraint olts_credential_ref_shape, valid for every new row)
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text("UPDATE olts SET credential_secret_ref = '10.0.0.1' WHERE name = 'FLT-OK'"))
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text("UPDATE olts SET credential_secret_ref = '0123456789abcdef0123456789abcdef' WHERE name = 'FLT-OK'"))


def test_inputs_are_validated_and_scoped_to_the_tenant(client, seed, inv, migrated):
    _on(migrated, seed["A"]); _on(migrated, seed["B"])
    ha, hb = hdr(client, "alice", seed, "A"), hdr(client, "bob", seed, "B")
    for bad in ({"vendor": "cisco"}, {"name": "x"}, {"name": "FLT  double"}, {"name": "FLT-../x"}, {"label": ""}, {"extra": 1}, {"edge_id": "not-a-uuid"}):
        assert client.post("/v1/fleet/olts", headers=ha, json=_body(inv, **bad)).status_code == 422, bad
    assert client.post("/v1/fleet/olts", headers=ha, json=_body(inv, name="FLT-E", edge_id="00000000-0000-0000-0000-000000000001")).status_code == 404   # unknown Edge
    assert client.post("/v1/fleet/olts", headers=ha, json=_body(inv, name="FLT-P", pop_id="00000000-0000-0000-0000-000000000001")).status_code == 404    # unknown POP
    # tenant B cannot register against tenant A's Edge, see A's OLT, nor use A's POP
    popa = client.post("/v1/pops", headers=ha, json={"name": "POP-T A"}).json()["id"]
    oa = client.post("/v1/fleet/olts", headers=ha, json=_body(inv, name="FLT-A", pop_id=popa)).json()["id"]
    assert client.post("/v1/fleet/olts", headers=hb, json=_body(inv, name="FLT-B")).status_code == 404
    assert client.get(f"/v1/fleet/olts/{oa}", headers=hb).status_code == 404
    assert client.patch(f"/v1/fleet/olts/{oa}", headers=hb, json={"label": "x"}).status_code == 404
    assert client.get("/v1/pops", headers=hb).json()["items"] == [] or all(x["id"] != popa for x in client.get("/v1/pops", headers=hb).json()["items"])
    assert client.patch(f"/v1/pops/{popa}", headers=hb, json={"note": "x"}).status_code == 404
    assert [x for x in client.get("/v1/fleet/olts", headers=hb).json()["items"] if x["id"] == oa] == []


def test_pops_are_unique_by_name_ignoring_case_and_editable(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    a = client.post("/v1/pops", headers=h, json={"name": "POP-T Norte"}).json()["id"]
    assert client.post("/v1/pops", headers=h, json={"name": "pop-t norte"}).status_code == 409
    b = client.post("/v1/pops", headers=h, json={"name": "POP-T Sul"}).json()["id"]
    assert client.patch(f"/v1/pops/{b}", headers=h, json={"name": "POP-T NORTE"}).status_code == 409
    assert client.patch(f"/v1/pops/{b}", headers=h, json={"code": "SUL", "note": None}).json()["code"] == "SUL"
    assert client.patch(f"/v1/pops/{b}", headers=h, json={"name": None}).status_code == 422
    assert client.post("/v1/pops", headers=h, json={"name": "POP-T Bad", "code": "bad code!"}).status_code == 422
    listed = {x["name"]: x for x in client.get("/v1/pops", headers=h).json()["items"]}
    assert listed["POP-T Norte"]["olts"] == 0 and a in {x["id"] for x in listed.values()}


def test_the_edge_adopts_a_registered_olt_and_keeps_the_registration(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    pid = client.post("/v1/pops", headers=h, json={"name": "POP-T Adota"}).json()["id"]
    o = client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-ADOPT", vendor="huawei", pop_id=pid, credential_ref="olt-adopt", label="L")).json()
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv, "a1", name="FLT-ADOPT"))
    assert r.status_code == 202, r.text
    got = client.get(f"/v1/fleet/olts/{o['id']}", headers=h).json()
    assert got["id"] == o["id"] and got["collected"] is True and (got["model"], got["firmware"], got["support_level"]) == ("MA5800-X7", "R018", "observed")
    assert got["pop"]["id"] == pid and got["has_credential_ref"] is True and got["label"] == "L" and got["registered"] is True   # the registration survives the first read
    # another Edge of the same provider cannot take over the registered name
    r2 = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a2"), json=snap(inv, "a2", name="FLT-ADOPT"))
    assert r2.status_code == 409 and "another edge" in r2.json()["detail"]


def test_audit_never_holds_the_credential_name(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    client.post("/v1/fleet/olts", headers=h, json=_body(inv, name="FLT-AUD", credential_ref="olt-audit-secretname"))
    with migrated.begin() as c:
        rows = c.execute(text("SELECT action, evidence_redacted::text AS e FROM audit_log WHERE action LIKE 'fleet.%' ORDER BY created_at")).all()
    assert any(r.action == "fleet.olt.registered" for r in rows)
    assert all("olt-audit-secretname" not in r.e for r in rows)
    assert any('"has_credential_ref": true' in r.e for r in rows)
