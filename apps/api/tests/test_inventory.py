
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import make_engine, scoped_connection
from tests.conftest import _now, agent, hdr, login, snap


def test_ingest_then_read_with_freshness(client, seed, inv):
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv))
    assert r.status_code == 202 and r.json()["onus"] == 2
    h = hdr(client, "alice", seed, "A")
    olts = client.get("/v1/olts", headers=h).json()
    olt1 = next(o for o in olts if o["name"] == "OLT-1")
    assert olt1["onu_count"] == 2 and olt1["freshness"] == "fresh" and olt1["support_level"] == "observed"
    onus = {o["serial"]: o for o in client.get("/v1/onus", headers=h).json()}
    assert onus["HWTC00000001"]["rx_dbm"] == -21.5 and onus["HWTC00000001"]["pon_path"] == "0/1/0"
    assert client.get("/v1/onus?serial=HWTC00000002", headers=h).json()[0]["status"] == "los"


def test_tenant_isolation_on_reads(client, seed, inv):
    client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv))
    hb = hdr(client, "bob", seed, "B")
    assert client.get("/v1/olts", headers=hb).json() == []
    assert client.get("/v1/onus", headers=hb).json() == []
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "b1"), json=snap(inv, "b1", name="OLT-1"))
    assert r.status_code == 202  # same OLT name in another tenant is independent
    assert len(client.get("/v1/olts", headers=hb).json()) == 1
    assert client.get("/v1/olts", headers=hdr(client, "alice", seed, "A")).json()[0]["onu_count"] == 2


def test_write_authorization(client, seed, inv):
    # token of edge a2 cannot push for edge a1; humans cannot push; agents cannot read
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a2"), json=snap(inv, "a1")).status_code == 403
    assert client.post("/v1/edge/olt-snapshots", headers=hdr(client, "alice", seed, "A"), json=snap(inv)).status_code == 403
    assert client.post("/v1/edge/olt-snapshots", json=snap(inv)).status_code == 401
    assert client.get("/v1/olts", headers=agent(client, inv, "a1")).status_code == 403


def test_read_permissions(client, seed):
    assert client.get("/v1/olts", headers=hdr(client, "dave", seed, "A")).status_code == 200  # noc_n1
    assert client.get("/v1/olts", headers={**login(client, "carol"), "X-Workspace-ID": str(seed["A"])}).status_code == 403  # auditor


def test_out_of_order_snapshot_never_overwrites_newer(client, seed, inv):
    a = agent(client, inv, "a1")
    new = snap(inv, name="OLT-OOO", observed=_now(-10), onus=[{"serial": "OOO1", "status": "online"}])
    old = snap(inv, name="OLT-OOO", observed=_now(-600), onus=[{"serial": "OOO1", "status": "offline"}])
    assert client.post("/v1/edge/olt-snapshots", headers=a, json=new).status_code == 202
    r = client.post("/v1/edge/olt-snapshots", headers=a, json=old)
    assert r.json()["status"] == "ignored_stale"
    h = hdr(client, "alice", seed, "A")
    assert client.get("/v1/onus?serial=OOO1", headers=h).json()[0]["status"] == "online"


def test_silence_means_stale_not_offline(client, seed, inv):
    old = snap(inv, name="OLT-OLD", observed=_now(-3600), onus=[{"serial": "OLD1", "status": "online"}])
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=old).status_code == 202
    h = hdr(client, "alice", seed, "A")
    onu = client.get("/v1/onus?serial=OLD1", headers=h).json()[0]
    assert onu["status"] == "online" and onu["freshness"] == "stale"  # last known state + explicit staleness


def test_validation_rejects_bad_input(client, inv):
    a = agent(client, inv, "a1")
    assert client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, observed=_now(3600))).status_code == 422
    assert client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, driver_level="certified")).status_code == 422
    bad = snap(inv, onus=[{"serial": "X", "status": "online", "rx_dbm": -200}])
    assert client.post("/v1/edge/olt-snapshots", headers=a, json=bad).status_code == 422
    assert client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, observed="2026-10-27T00:00:00")).status_code == 422


def test_olt_name_cannot_be_hijacked_by_other_edge_of_same_tenant(client, inv):
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv, name="OLT-OWN")).status_code == 202
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a2"), json=snap(inv, "a2", name="OLT-OWN"))
    assert r.status_code == 409


def test_certified_cannot_be_downgraded_or_self_declared(client, seed, inv, migrated):
    a = agent(client, inv, "a1")
    client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, name="OLT-CERT"))
    with migrated.begin() as c:  # homologation is an owner-side action
        c.execute(text("UPDATE olts SET support_level='certified' WHERE name='OLT-CERT'"))
    client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, name="OLT-CERT", driver_level="identified"))
    olts = {o["name"]: o for o in client.get("/v1/olts", headers=hdr(client, "alice", seed, "A")).json()}
    assert olts["OLT-CERT"]["support_level"] == "certified"


def test_runtime_role_cannot_delete_inventory(seed, app_url):
    eng = make_engine(app_url)
    for t in ("onus", "olts", "pon_ports", "cpes"):
        with pytest.raises(DBAPIError), scoped_connection(eng, tenant_id=seed["A"]) as c:
            c.execute(text(f"DELETE FROM {t}"))  # noqa: S608


def test_cpe_snapshot_and_binding_conflict(client, seed, inv):
    a = agent(client, inv, "a1")
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": "HWTC00000001", "vendor": "Huawei", "model": "HG8245H",
         "binding": {"protocol": "tr069", "external_id": "00259E-HG8245H-ZTEG00000001", "connector_id": "genieacs-lab"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=a, json=body).status_code == 202
    assert client.post("/v1/edge/cpe-snapshots", headers=a, json=body).status_code == 202  # idempotent
    rows = client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json()
    assert len(rows) == 1 and rows[0]["bindings"][0]["protocol"] == "tr069" and rows[0]["freshness"] == "fresh"
    clash = {**body, "cpes": [{**body["cpes"][0], "canonical_serial": "OTHER-SERIAL"}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=a, json=clash).status_code == 409
    assert client.get("/v1/cpes", headers=hdr(client, "bob", seed, "B")).json() == []


def test_snapshot_emits_outbox_event(client, seed, inv, migrated):
    client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv, name="OLT-EVT"))
    with migrated.connect() as c:
        n = c.execute(text("SELECT count(*) FROM events_outbox WHERE event_type='olt.snapshot_ingested' AND tenant_id=:t"),
                      {"t": seed["A"]}).scalar()
    assert n >= 1


def test_cpe_cannot_be_overwritten_by_another_edge(client, seed, inv):
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": "OWNED-CPE-1", "vendor": "Huawei",
         "binding": {"protocol": "tr069", "external_id": "own-1", "connector_id": "genieacs-a1"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    evil = {**body, "edge_id": str(inv["a2"]["edge"]), "cpes": [{**body["cpes"][0], "vendor": "HACKED",
            "binding": {"protocol": "tr069", "external_id": "own-2", "connector_id": "genieacs-a2"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "a2"), json=evil).status_code == 409
    rows = {c["canonical_serial"]: c for c in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json()}
    assert rows["OWNED-CPE-1"]["vendor"] == "Huawei" and len(rows["OWNED-CPE-1"]["bindings"]) == 1


def test_db_rejects_onu_pointing_to_pon_of_another_olt(client, seed, inv, migrated):
    a = agent(client, inv, "a1")
    client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, name="OLT-FK1"))
    client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, name="OLT-FK2"))
    with migrated.begin() as c:
        pon_other = c.execute(text("SELECT p.id FROM pon_ports p JOIN olts o ON o.id=p.olt_id WHERE o.name='OLT-FK2'")).scalar()
        onu_id = c.execute(text("SELECT u.id FROM onus u JOIN olts o ON o.id=u.olt_id WHERE o.name='OLT-FK1' LIMIT 1")).scalar()
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("UPDATE onus SET pon_id=:p WHERE id=:i"), {"p": pon_other, "i": onu_id})


def test_unknown_pon_path_leaves_onu_without_pon(client, seed, inv):
    s = snap(inv, name="OLT-NOPON", onus=[{"serial": "NP1", "pon_path": "9/9/9", "status": "online"}])
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=s).status_code == 202
    onu = client.get("/v1/onus?serial=NP1", headers=hdr(client, "alice", seed, "A")).json()[0]
    assert onu["pon_path"] is None


def test_large_batch_ingests_in_one_request_and_limits_hold(client, seed, inv):
    a = agent(client, inv, "a1")
    onus = [{"serial": f"BULK{i:05d}", "pon_path": "0/1/0", "status": "online", "rx_dbm": -20.0} for i in range(5000)]
    assert client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, name="OLT-BULK", onus=onus)).status_code == 202
    too_many = onus + [{"serial": "EXTRA", "status": "online"}]
    assert client.post("/v1/edge/olt-snapshots", headers=a, json=snap(inv, name="OLT-BULK", onus=too_many)).status_code == 422
    big = {"padding": "x" * (9 * 1024 * 1024)}
    assert client.post("/v1/edge/olt-snapshots", headers=a, json=big).status_code == 413


def test_stale_cpe_snapshot_does_not_touch_bindings(client, seed, inv):
    a = agent(client, inv, "a1")
    def cpe(ext, observed):
        return {"edge_id": str(inv["a1"]["edge"]), "observed_at": observed, "cpes": [
            {"canonical_serial": "OOO-CPE", "vendor": "V",
             "binding": {"protocol": "tr069", "external_id": ext, "connector_id": "genieacs-ooo"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=a, json=cpe("ext-new", _now(-10))).status_code == 202
    r = client.post("/v1/edge/cpe-snapshots", headers=a, json=cpe("ext-old", _now(-900)))
    assert r.json()["status"] == "ignored_stale"
    row = next(c for c in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json() if c["canonical_serial"] == "OOO-CPE")
    assert [b["external_id"] for b in row["bindings"]] == ["ext-new"]


def test_concurrent_new_cpe_from_two_edges_has_single_owner(client, seed, inv, migrated):
    import threading
    results = {}

    def push(key):
        body = {"edge_id": str(inv[key]["edge"]), "observed_at": _now(), "cpes": [
            {"canonical_serial": "RACE-CPE", "vendor": key,
             "binding": {"protocol": "tr069", "external_id": f"race-{key}", "connector_id": f"c-{key}"}}]}
        results[key] = client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, key), json=body).status_code

    for _ in range(5):
        with migrated.begin() as c:
            c.execute(text("DELETE FROM cpes WHERE canonical_serial='RACE-CPE'"))
        results.clear()
        ts = [threading.Thread(target=push, args=(k,)) for k in ("a1", "a2")]
        [t.start() for t in ts]
        [t.join() for t in ts]
        with migrated.connect() as c:
            rows = c.execute(text(
                "SELECT c.edge_id, b.external_id FROM cpes c LEFT JOIN cpe_protocol_bindings b ON b.cpe_id=c.id "
                "WHERE c.canonical_serial='RACE-CPE'")).all()
        owners = {r.edge_id for r in rows}
        assert len(owners) == 1, rows                      # single owner
        assert all(r.external_id in (None, f"race-{'a1' if r.edge_id == inv['a1']['edge'] else 'a2'}") for r in rows), rows
        assert 202 in results.values()


def test_go_edge_olt_payload_is_accepted_by_the_api(client, seed, inv):
    """Cross-language contract: the exact JSON emitted by the Go Edge collector (golden) must be ingestible."""
    import json
    from pathlib import Path
    golden = json.loads((Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "edge" / "olt_snapshot_huawei.golden.json").read_text())
    golden.update(edge_id=str(inv["a1"]["edge"]), observed_at=_now(), name="OLT-GO-GOLDEN")
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=golden)
    assert r.status_code == 202, r.text
    h = hdr(client, "alice", seed, "A")
    onus = {o["serial"]: o for o in client.get("/v1/onus?limit=1000", headers=h).json() if o["serial"].startswith("48575443")}
    assert onus["48575443A1B2C3D4"]["status"] == "online" and onus["48575443A1B2C3D4"]["rx_dbm"] == -21.5
    assert onus["48575443A1B2C3D5"]["status"] == "offline" and onus["48575443A1B2C3D5"]["rx_dbm"] is None
    olt = next(o for o in client.get("/v1/olts", headers=h).json() if o["name"] == "OLT-GO-GOLDEN")
    assert olt["support_level"] == "identified" and olt["firmware"] == "R018"


def test_a_serial_claim_with_another_external_id_is_ignored_not_merged(client, seed, inv):
    """A CPE is identified by what it CLAIMS. A second device claiming an existing serial under a different external id must not
    gain a binding on that CPE nor rewrite its vendor/model; the rest of the batch still goes through."""
    a = agent(client, inv, "a1")

    def cpe(serial, ext, vendor="Huawei"):
        return {"canonical_serial": serial, "vendor": vendor, "model": "M",
                "binding": {"protocol": "tr069", "external_id": ext, "connector_id": "genieacs-claims"}}

    base = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(-5), "cpes": [cpe("CLAIM-VICTIM-1", "legit-ext-1")]}
    assert client.post("/v1/edge/cpe-snapshots", headers=a, json=base).status_code == 202
    hostile = {**base, "observed_at": _now(), "cpes": [cpe("CLAIM-VICTIM-1", "hostile-ext", "HACKED"), cpe("CLAIM-OTHER-1", "legit-ext-2"),
                                                       cpe("CLAIM-DUP-1", "dup-a"), cpe("CLAIM-DUP-1", "dup-b")]}
    r = client.post("/v1/edge/cpe-snapshots", headers=a, json=hostile)
    assert r.status_code == 202 and r.json()["conflicts"] == 3 and r.json()["cpes"] == 1, r.text  # victim claim + both dup claims
    rows = {c["canonical_serial"]: c for c in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json()}
    assert rows["CLAIM-VICTIM-1"]["vendor"] == "Huawei" and [b["external_id"] for b in rows["CLAIM-VICTIM-1"]["bindings"]] == ["legit-ext-1"]
    assert "CLAIM-OTHER-1" in rows and "CLAIM-DUP-1" not in rows
    again = {**base, "observed_at": _now(2)}  # the legitimate device re-informing keeps updating normally
    assert client.post("/v1/edge/cpe-snapshots", headers=a, json=again).json()["conflicts"] == 0
