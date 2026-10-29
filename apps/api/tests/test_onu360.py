"""ONU 360: one ONU with its origin, PON context, open incident and (only for customers:read roles, audited) its subscriber."""
from sqlalchemy import text

from tests.conftest import agent, hdr, snap


def _onu(client, h, serial):
    return client.get(f"/v1/onus?serial={serial}", headers=h).json()[0]


def _seed_onu(client, inv, name, serial="O360-1"):
    onus = [{"serial": serial, "pon_path": "0/3/0", "status": "online", "rx_dbm": -19.25},
            {"serial": serial + "B", "pon_path": "0/3/0", "status": "offline", "rx_dbm": None}]
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"),
                    json=snap(inv, name=name, pons=[{"pon_path": "0/3/0", "status": "up"}], onus=onus))
    assert r.status_code == 202, r.text


def _audit_count(migrated, tenant, onu_id):
    with migrated.begin() as c:
        return c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'onu360.view' AND target_id = :i AND tenant_id = :t"),
                         {"i": str(onu_id), "t": tenant}).scalar()


def test_onu360_basic_with_pon_context_and_origin(client, seed, inv):
    _seed_onu(client, inv, "OLT-360")
    h = hdr(client, "alice", seed, "A")
    u = _onu(client, h, "O360-1")
    d = client.get(f"/v1/onus/{u['id']}", headers=h).json()
    assert d["serial"] == "O360-1" and d["status"] == "online" and d["rx_dbm"] == -19.25 and d["freshness"] == "fresh"
    assert d["olt"]["name"] == "OLT-360" and d["olt"]["support_level"] == "observed"
    assert d["pon"] == {"path": "0/3/0", "onus": 2, "online": 1}
    assert d["incident"] is None and d["source"] == "olt_snapshot"
    assert d["customer"] == {"association": "none", "pending_suggestions": 0}


def test_customer_section_only_for_customers_read_and_every_view_audited(client, seed, inv, migrated):
    _seed_onu(client, inv, "OLT-360B", "O360-2")
    ha, hd = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")  # dave = noc_n1: inventory yes, customers no
    onu = _onu(client, ha, "O360-2")
    with migrated.begin() as c:
        cid = c.execute(text("INSERT INTO customers(tenant_id, erp_source, erp_customer_id, display_name, document_last4, contract_status) "
                             "VALUES (:t,'csv','C360','Cliente Teste 360','1234','active') RETURNING id"), {"t": seed["A"]}).scalar()
        c.execute(text("INSERT INTO associations(tenant_id, onu_id, customer_id, status, score, evidence, reviewed_by, reviewed_at) "
                       "VALUES (:t,:o,:c,'approved',100,CAST('{}' AS jsonb),:r,now())"),
                  {"t": seed["A"], "o": onu["id"], "c": cid, "r": seed["alice"]})
    before = _audit_count(migrated, seed["A"], onu["id"])
    d = client.get(f"/v1/onus/{onu['id']}", headers=ha).json()
    assert d["customer"]["association"] == "approved" and d["customer"]["display_name"] == "Cliente Teste 360"
    assert d["customer"]["document_last4"] == "1234" and d["customer"]["contract_status"] == "active"
    assert _audit_count(migrated, seed["A"], onu["id"]) == before + 1  # viewing personal data leaves a trace
    nd = client.get(f"/v1/onus/{onu['id']}", headers=hd)
    assert nd.status_code == 200 and nd.json()["customer"] is None  # no personal data without customers:read
    assert "Cliente Teste 360" not in nd.text and _audit_count(migrated, seed["A"], onu["id"]) == before + 1


def test_onu360_open_incident_and_tenant_isolation(client, seed, inv, migrated):
    _seed_onu(client, inv, "OLT-360C", "O360-3")
    ha = hdr(client, "alice", seed, "A")
    onu = _onu(client, ha, "O360-3")
    with migrated.begin() as c:
        row = c.execute(text("SELECT olt_id, pon_id FROM onus WHERE id = :i"), {"i": onu["id"]}).one()
        iid = c.execute(text("INSERT INTO incidents(tenant_id, kind, olt_id, pon_id, dedupe_key, suspected_cause, evidence) "
                             "VALUES (:t,'pon_mass_outage',:o,:p,'k-360','power',CAST('{}' AS jsonb)) RETURNING id"),
                        {"t": seed["A"], "o": row.olt_id, "p": row.pon_id}).scalar()
        c.execute(text("INSERT INTO incident_onus(tenant_id, incident_id, onu_id) VALUES (:t,:i,:u)"),
                  {"t": seed["A"], "i": iid, "u": onu["id"]})
    d = client.get(f"/v1/onus/{onu['id']}", headers=ha).json()
    assert d["incident"]["id"] == str(iid) and d["incident"]["suspected_cause"] == "power"
    assert client.get(f"/v1/onus/{onu['id']}", headers=hdr(client, "bob", seed, "B")).status_code == 404  # other tenant: RLS
    assert client.get("/v1/onus/00000000-0000-0000-0000-000000000000", headers=ha).status_code == 404
    assert client.get("/v1/onus/not-a-uuid", headers=ha).status_code == 422
    assert client.get(f"/v1/onus/{onu['id']}", headers=agent(client, inv, "a1")).status_code == 403  # agents never read
