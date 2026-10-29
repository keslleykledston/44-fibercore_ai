"""ONU<->CPE links by evidence + Customer Context (ADR-0021, FC22-004): flags, RBAC, A/B isolation, ambiguity, one-confirmed rules, audit, status."""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import _now, agent, hdr, snap

PFX = "CTX-"


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features"))
        c.execute(text("DELETE FROM onu_cpe_links"))
        c.execute(text("DELETE FROM associations WHERE customer_id IN (SELECT id FROM customers WHERE erp_source = 'ctxtest')"))
        c.execute(text("DELETE FROM customers WHERE erp_source = 'ctxtest'"))
        c.execute(text("DELETE FROM cpe_protocol_bindings WHERE cpe_id IN (SELECT id FROM cpes WHERE canonical_serial LIKE 'CTX-%')"))
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'CTX-%'"))
        c.execute(text("DELETE FROM onus WHERE serial LIKE 'CTX-%'"))
        c.execute(text("DELETE FROM pon_ports WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-CTX-%')"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-CTX-%'"))
        c.execute(text("DELETE FROM tenant_memberships WHERE role = 'support'"))


def _flags(migrated, tenant, *names):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        for n in names:
            c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,true)"), {"t": tenant, "f": n})


def _olt(client, inv, key, name, serial):
    onus = [{"serial": serial, "pon_path": "0/5/0", "status": "online", "rx_dbm": -20.5}]
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, key),
                    json=snap(inv, key, name=name, pons=[{"pon_path": "0/5/0", "status": "up"}], onus=onus))
    assert r.status_code == 202, r.text


def _cpe(client, inv, key, serial):
    body = {"edge_id": str(inv[key]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": serial, "vendor": "Vendor", "model": "Model", "firmware": "1.0",
         "binding": {"protocol": "tr069", "external_id": f"ext-{serial.lower()}", "connector_id": f"c-{serial.lower()}"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, key), json=body).status_code == 202


def _onu(client, h, serial):
    return next(o for o in client.get(f"/v1/onus?serial={serial}", headers=h).json())


def _customer(migrated, tenant, onu_id, reviewer, updated="now()"):
    with migrated.begin() as c:
        cid = c.execute(
            text(f"INSERT INTO customers(tenant_id, erp_source, erp_customer_id, display_name, document_last4, contract_status, "  # noqa: S608
                 f"source_updated_at) VALUES (:t,'ctxtest',:e,'Cliente Contexto','9876','active',{updated}) RETURNING id"),
            {"t": tenant, "e": f"E{onu_id}"}).scalar()
        if onu_id:
            c.execute(text("INSERT INTO associations(tenant_id, onu_id, customer_id, status, score, evidence, reviewed_by, reviewed_at) "
                           "VALUES (:t,:o,:c,'approved',100,CAST('{}' AS jsonb),:r,now())"),
                      {"t": tenant, "o": onu_id, "c": cid, "r": reviewer})
    return cid


def _setup(client, inv, seed, migrated, serial="CTX-0001"):
    _flags(migrated, seed["A"], "onu_cpe_links", "customer_context")
    _olt(client, inv, "a1", "OLT-CTX-A", serial)
    _cpe(client, inv, "a1", serial)
    return hdr(client, "alice", seed, "A")


def _suggest(client, h):
    r = client.post("/v1/onu-cpe-links/suggest", headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _links(client, h, **params):
    """Only this module's links: other modules leave CPEs/ONUs with equal serials in the shared tenant."""
    rows = client.get("/v1/onu-cpe-links", headers=h, params={"limit": 1000, **params}).json()
    return [x for x in rows if x["onu"]["serial"].startswith(PFX)]


def test_everything_is_off_by_default(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    for method, url in (("post", "/v1/onu-cpe-links/suggest"), ("get", "/v1/onu-cpe-links"),
                        ("post", "/v1/onu-cpe-links/00000000-0000-0000-0000-000000000000/confirm"),
                        ("get", "/v1/customers/00000000-0000-0000-0000-000000000000/context")):
        r = getattr(client, method)(url, headers=h)
        assert r.status_code == 403 and r.json()["detail"] == "feature_disabled", url
    _olt(client, inv, "a1", "OLT-CTX-OFF", "CTX-OFF1")
    assert "cpe" not in client.get(f"/v1/onus/{_onu(client, h, 'CTX-OFF1')['id']}", headers=h).json()


def test_suggest_is_evidence_based_idempotent_and_never_confirms(client, seed, inv, migrated):
    h = _setup(client, inv, seed, migrated)
    _olt(client, inv, "a1", "OLT-CTX-A", "CTX-NOCPE")  # an ONU without a matching CPE is not suggested
    first = _suggest(client, h)
    assert first["created"] >= 1 and first["limit_reached"] is False
    assert _suggest(client, h) == {"created": 0, "examined": 0, "limit_reached": False}  # idempotent; known pairs do not eat the cap
    links = _links(client, h)
    assert len(links) == 1
    link = links[0]
    assert link["status"] == "suggested" and link["confidence"] == 0.5 and link["reviewed_at"] is None
    assert link["evidence"]["rule"] == "serial_equal" and link["evidence"]["ambiguous"] is False
    assert link["onu"]["serial"] == "CTX-0001" and link["cpe"]["canonical_serial"] == "CTX-0001"
    onu = _onu(client, h, "CTX-0001")
    blk = client.get(f"/v1/onus/{onu['id']}", headers=h).json()["cpe"]
    assert blk == {"link": "suggested", "pending_suggestions": 1, "can_review": True, "device": None, "provenance": None,
                   "suggestions": [{"id": link["id"], "confidence": 0.5, "rule": "serial_equal", "ambiguous": False}]}
    assert client.get(f"/v1/onus/{onu['id']}", headers=hdr(client, "dave", seed, "A")).json()["cpe"]["can_review"] is False  # noc_n1 reads only
    assert _links(client, h, status="confirmed") == []


def test_confirm_reject_audit_outbox_and_one_way_state(client, seed, inv, migrated):
    h = _setup(client, inv, seed, migrated)
    _suggest(client, h)
    lid = _links(client, h)[0]["id"]
    r = client.post(f"/v1/onu-cpe-links/{lid}/confirm", headers=h)
    assert r.status_code == 200 and r.json() == {"id": lid, "status": "confirmed"}
    assert client.post(f"/v1/onu-cpe-links/{lid}/confirm", headers=h).status_code == 409
    assert client.post(f"/v1/onu-cpe-links/{lid}/reject", headers=h).status_code == 409
    assert client.post(f"/v1/onu-cpe-links/{lid}/confirm", headers=hdr(client, "bob", seed, "B")).status_code in (403, 404)
    with migrated.begin() as c:
        row = c.execute(text("SELECT status, reviewed_by FROM onu_cpe_links WHERE id = :i"), {"i": lid}).one()
        assert row.status == "confirmed" and row.reviewed_by == seed["alice"]
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'onu_cpe_link.confirmed' AND target_id = :i"), {"i": lid}).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM events_outbox WHERE event_type = 'onu_cpe_link.confirmed' AND aggregate_id = :i"),
                         {"i": lid}).scalar() == 1
    d = client.get(f"/v1/onus/{_onu(client, h, 'CTX-0001')['id']}", headers=h).json()["cpe"]
    assert d["link"] == "confirmed" and d["device"]["vendor"] == "Vendor" and d["device"]["protocols"] == ["tr069"]
    assert d["provenance"]["source"] == "genieacs_nbi"
    blob = json.dumps(d)
    assert "ext-ctx-0001" not in blob and "c-ctx-0001" not in blob  # binding ids stay server-side


def test_reject_closes_the_suggestion_and_resuggest_does_not_reopen(client, seed, inv, migrated):
    h = _setup(client, inv, seed, migrated)
    _suggest(client, h)
    lid = _links(client, h)[0]["id"]
    assert client.post(f"/v1/onu-cpe-links/{lid}/reject", headers=h).json()["status"] == "rejected"
    assert _suggest(client, h)["created"] == 0  # a person said no: the machine does not ask again
    assert client.get(f"/v1/onus/{_onu(client, h, 'CTX-0001')['id']}", headers=h).json()["cpe"]["link"] == "none"


def test_ambiguous_serial_on_two_olts_cannot_be_confirmed(client, seed, inv, migrated):
    h = _setup(client, inv, seed, migrated, "CTX-AMB1")
    _olt(client, inv, "a2", "OLT-CTX-A2", "CTX-AMB1")  # same serial on a second OLT
    _suggest(client, h)
    links = _links(client, h)
    assert len(links) == 2
    assert all(x["confidence"] == 0.2 and x["evidence"]["ambiguous"] is True for x in links)
    r = client.post(f"/v1/onu-cpe-links/{links[0]['id']}/confirm", headers=h)
    assert r.status_code == 409 and "ambiguous" in r.json()["detail"]


def test_database_allows_only_one_confirmed_per_onu_and_per_cpe(client, seed, inv, migrated):
    _setup(client, inv, seed, migrated)
    _cpe(client, inv, "a1", "CTX-0002")
    _olt(client, inv, "a1", "OLT-CTX-A", "CTX-0003")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        ids = {r.serial: r.id for r in c.execute(text("SELECT id, serial FROM onus WHERE serial IN ('CTX-0001','CTX-0003')"))}
        cpes = {r.canonical_serial: r.id for r in c.execute(text("SELECT id, canonical_serial FROM cpes WHERE canonical_serial LIKE 'CTX-%'"))}
        ev = "CAST('{\"rule\":\"serial_equal\"}' AS jsonb)"
        ins = ("INSERT INTO onu_cpe_links(tenant_id, onu_id, cpe_id, status, confidence, evidence, reviewed_by, reviewed_at) "  # noqa: S608
               f"VALUES (:t,:o,:c,'confirmed',0.9,{ev},:r,now())")
        c.execute(text(ins), {"t": seed["A"], "o": ids["CTX-0001"], "c": cpes["CTX-0001"], "r": seed["alice"]})
    for onu, cpe in (("CTX-0001", "CTX-0002"), ("CTX-0003", "CTX-0001")):  # same ONU / same CPE again
        with pytest.raises(DBAPIError) as ex, migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(ins), {"t": seed["A"], "o": ids[onu], "c": cpes[cpe], "r": seed["alice"]})
        assert "unique" in str(ex.value).lower(), ex.value  # the one-confirmed index, not some other error
    with pytest.raises(DBAPIError) as ex, migrated.begin() as c:  # a suggestion cannot carry a reviewer
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO onu_cpe_links(tenant_id, onu_id, cpe_id, status, confidence, evidence, reviewed_by) "
                       "VALUES (:t,:o,:c,'suggested',0.5,CAST('{\"rule\":\"serial_equal\"}' AS jsonb),:r)"),
                  {"t": seed["A"], "o": ids["CTX-0003"], "c": cpes["CTX-0002"], "r": seed["alice"]})
    assert "check" in str(ex.value).lower(), ex.value
    for evidence in ("{}", '{"rule": 7}', '{"other": "x"}'):  # a link must carry the rule that produced it: no evidence, no link (any status)
        with pytest.raises(DBAPIError) as ex, migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text("INSERT INTO onu_cpe_links(tenant_id, onu_id, cpe_id, status, confidence, evidence) "
                           "VALUES (:t,:o,:c,'suggested',0.5,CAST(:e AS jsonb))"),
                      {"t": seed["A"], "o": ids["CTX-0003"], "c": cpes["CTX-0002"], "e": evidence})
        assert "check" in str(ex.value).lower(), ex.value


def test_rbac_and_tenant_isolation(client, seed, inv, migrated):
    h = _setup(client, inv, seed, migrated)
    _suggest(client, h)
    hd = hdr(client, "dave", seed, "A")  # noc_n1: reads inventory, cannot review
    assert client.post("/v1/onu-cpe-links/suggest", headers=hd).status_code == 403
    assert client.get("/v1/onu-cpe-links", headers=hd).status_code == 200
    lid = _links(client, h)[0]["id"]
    assert client.post(f"/v1/onu-cpe-links/{lid}/confirm", headers=hd).status_code == 403
    assert client.post("/v1/onu-cpe-links/suggest", headers=agent(client, inv, "a1")).status_code == 403
    _flags(migrated, seed["B"], "onu_cpe_links")
    hb = hdr(client, "bob", seed, "B")
    assert _links(client, hb) == []  # B sees none of A's links (RLS)
    assert _suggest(client, hb)["created"] == 0
    assert client.get("/v1/onu-cpe-links?status=bogus", headers=h).status_code == 422


def test_customer_context_status_precedence_and_no_secrets(client, seed, inv, migrated):
    h = _setup(client, inv, seed, migrated)
    onu = _onu(client, h, "CTX-0001")
    nobody = _customer(migrated, seed["A"], None, seed["alice"])
    unknown = client.get(f"/v1/customers/{nobody}/context", headers=h).json()
    assert unknown["status"] == "unknown" and unknown["onus"] == []  # nothing a person approved => nothing is claimed
    cid = _customer(migrated, seed["A"], onu["id"], seed["alice"])
    d = client.get(f"/v1/customers/{cid}/context", headers=h).json()
    assert d["status"] == "partial" and d["onus"][0]["cpe"]["link"] == "none"
    assert d["customer"]["provenance"]["source"] == "erp:ctxtest" and d["customer"]["provenance"]["quality"] == "fresh"
    _suggest(client, h)
    lid = _links(client, h)[0]["id"]
    assert client.get(f"/v1/customers/{cid}/context", headers=h).json()["onus"][0]["cpe"]["pending_suggestions"] == 1
    client.post(f"/v1/onu-cpe-links/{lid}/confirm", headers=h)
    full = client.get(f"/v1/customers/{cid}/context", headers=h).json()
    assert full["status"] == "complete" and full["onus"][0]["cpe"]["link"] == "confirmed"
    blob = json.dumps(full).lower()
    for forbidden in ("document_hmac", "erp_customer_id", "psk", "password", "external_id", "ext-ctx-0001", "e" + str(onu["id"])):
        assert forbidden not in blob
    with migrated.begin() as c:  # ERP data older than its TTL turns the whole context stale
        c.execute(text("UPDATE customers SET source_updated_at = now() - interval '30 days' WHERE id = :i"), {"i": cid})
    assert client.get(f"/v1/customers/{cid}/context", headers=h).json()["status"] == "stale"


def test_customer_context_is_audited_rbac_isolated_and_404(client, seed, inv, migrated):
    h = _setup(client, inv, seed, migrated)
    cid = _customer(migrated, seed["A"], _onu(client, h, "CTX-0001")["id"], seed["alice"])

    def views():
        with migrated.begin() as c:
            return c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'customer.context.view' AND target_id = :i"),
                             {"i": str(cid)}).scalar()
    before = views()
    assert client.get(f"/v1/customers/{cid}/context", headers=h).status_code == 200
    assert views() == before + 1  # personal data: every read leaves a trace
    assert client.get(f"/v1/customers/{cid}/context", headers=hdr(client, "dave", seed, "A")).status_code == 403  # noc_n1: no customers:read
    _flags(migrated, seed["B"], "customer_context")
    assert client.get(f"/v1/customers/{cid}/context", headers=hdr(client, "bob", seed, "B")).status_code == 404  # RLS: not B's customer
    assert client.get("/v1/customers/00000000-0000-0000-0000-000000000000/context", headers=h).status_code == 404
    assert client.get("/v1/customers/not-a-uuid/context", headers=h).status_code == 422


def test_incident_needs_incidents_read_and_is_marked_hidden_otherwise(client, seed, inv, migrated):
    _flags(migrated, seed["B"], "customer_context")
    _olt(client, inv, "b1", "OLT-CTX-B", "CTX-B001")
    hb = hdr(client, "bob", seed, "B")
    onu = _onu(client, hb, "CTX-B001")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
        c.execute(text("INSERT INTO tenant_memberships VALUES (:t,:u,'support')"), {"t": seed["B"], "u": seed["dave"]})  # customers:read only
    cid = _customer(migrated, seed["B"], onu["id"], seed["bob"])
    admin = client.get(f"/v1/customers/{cid}/context", headers=hb).json()["onus"][0]
    assert admin["incident_hidden"] is False and admin["incident"] is None
    support = client.get(f"/v1/customers/{cid}/context", headers=hdr(client, "dave", seed, "B"))
    assert support.status_code == 200
    assert support.json()["onus"][0]["incident_hidden"] is True  # absence of the field must not read as "no incident"


def test_every_table_the_context_reads_has_forced_rls_and_a_tenant_policy(migrated):
    """The context queries filter by id only; the isolation is the database's. Prove it for each relation, not by assumption."""
    tables = ["customers", "associations", "onus", "olts", "pon_ports", "incidents", "incident_onus", "cpes", "cpe_protocol_bindings",
              "onu_cpe_links", "tenant_features"]
    with migrated.begin() as c:
        rows = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in c.execute(
            text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = ANY(:t) AND relkind = 'r'"), {"t": tables})}
        pols = {r.tablename for r in c.execute(text("SELECT DISTINCT tablename FROM pg_policies WHERE tablename = ANY(:t)"), {"t": tables})}
    assert set(rows) == set(tables)
    assert all(v == (True, True) for v in rows.values()), rows
    assert pols == set(tables)


def test_flags_are_independent_links_show_the_cpe_on_onu360_while_the_customer_context_stays_off(client, seed, inv, migrated):
    _flags(migrated, seed["A"], "onu_cpe_links")  # customer_context stays at its default (off)
    _olt(client, inv, "a1", "OLT-CTX-A", "CTX-IND1")
    h = hdr(client, "alice", seed, "A")
    assert client.get(f"/v1/onus/{_onu(client, h, 'CTX-IND1')['id']}", headers=h).json()["cpe"]["link"] == "none"
    cid = _customer(migrated, seed["A"], None, seed["alice"])
    r = client.get(f"/v1/customers/{cid}/context", headers=h)
    assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
