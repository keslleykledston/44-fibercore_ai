
import json
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
    r = client.post("/v1/edge/cpe-snapshots", headers=a, json=clash)  # re-pointing a binding to another serial is ignored+counted, not merged
    assert r.status_code == 202 and r.json()["conflicts"] == 1 and r.json()["cpes"] == 0
    assert "OTHER-SERIAL" not in {c["canonical_serial"] for c in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json()}
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


def test_serial_is_stored_in_one_canonical_form_and_the_database_enforces_it(client, seed, inv, migrated):
    a = agent(client, inv, "a1")
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": "  canon-case-1 ", "vendor": "V", "binding": {"protocol": "tr069", "external_id": "canon-ext", "connector_id": "c-canon"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=a, json=body).status_code == 202
    again = {**body, "observed_at": _now(3), "cpes": [{**body["cpes"][0], "canonical_serial": "CANON-CASE-1"}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=a, json=again).json()["conflicts"] == 0  # same device, not a second one
    rows = [c for c in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json() if c["canonical_serial"].startswith("CANON-CASE")]
    assert [c["canonical_serial"] for c in rows] == ["CANON-CASE-1"]
    with pytest.raises(DBAPIError), migrated.begin() as c:  # even a bypass of the API cannot store a non-canonical serial
        c.execute(text("INSERT INTO cpes (tenant_id, edge_id, canonical_serial) VALUES (:t,:e,'lower-case-x')"),
                  {"t": seed["A"], "e": inv["a1"]["edge"]})


def test_concurrent_snapshots_cannot_attach_two_external_ids_to_one_new_serial(client, seed, inv, migrated):
    import threading

    a = agent(client, inv, "a1")
    out: dict = {}
    obs = _now()  # one instant for all: none of them can be "stale" relative to the others

    def post(ext):
        body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": obs, "cpes": [
            {"canonical_serial": "RACE-CLAIM-1", "binding": {"protocol": "tr069", "external_id": ext, "connector_id": "c-race"}}]}
        out[ext] = client.post("/v1/edge/cpe-snapshots", headers=a, json=body)

    ts = [threading.Thread(target=post, args=(e,)) for e in ("race-a", "race-b", "race-c", "race-d")]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert all(r.status_code == 202 for r in out.values()), {k: r.text for k, r in out.items()}
    with migrated.begin() as c:
        n = c.execute(text("SELECT count(*) FROM cpe_protocol_bindings b JOIN cpes p ON p.id = b.cpe_id "
                           "WHERE p.canonical_serial = 'RACE-CLAIM-1' AND p.tenant_id = :t"), {"t": seed["A"]}).scalar()
    assert n == 1  # exactly one claim won; the others were ignored, none merged
    assert sum(r.json()["conflicts"] for r in out.values()) == 3


def test_overlapping_batches_in_parallel_do_not_deadlock(client, seed, inv):
    import random
    import threading

    a = agent(client, inv, "a1")
    serials = [f"OVERLAP-{i:03d}" for i in range(12)]
    obs = _now()
    out: list = []

    def post(seed_n):
        rnd = random.Random(seed_n)  # noqa: S311 - deterministic test data, not security
        pick = rnd.sample(serials, 8)  # different, partially overlapping subsets; the API must order the locks itself
        body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": obs, "cpes": [
            {"canonical_serial": s, "binding": {"protocol": "tr069", "external_id": f"ov-{s}", "connector_id": "c-overlap"}} for s in pick]}
        out.append(client.post("/v1/edge/cpe-snapshots", headers=a, json=body).status_code)

    ts = [threading.Thread(target=post, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert out == [202] * 8, out


def test_claim_locks_are_taken_in_sorted_order(client, seed, inv):
    """The deadlock guarantee is the ORDER of acquisition: the advisory lock statements must run sorted by claim key whatever the order
    of the CPEs in the request."""
    from sqlalchemy import event

    from app.core.db import get_engine

    seen: list = []

    def spy(conn, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock" in statement:
            seen.append(parameters)

    eng = get_engine()
    event.listen(eng, "before_cursor_execute", spy)
    try:
        serials = [f"ORDER-{c}" for c in "ZYXWVUTSRQ"]  # deliberately reverse-sorted in the request
        body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
            {"canonical_serial": s, "binding": {"protocol": "tr069", "external_id": f"o-{s}", "connector_id": "c-order"}} for s in serials]}
        assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    finally:
        event.remove(eng, "before_cursor_execute", spy)
    ks = [p["k"] for params in seen for p in (params if isinstance(params, list) else [params])]
    ks = [k for k in ks if "|c-order|" in k]  # the login throttle takes advisory locks too (ip:/svc: keys); only the claim keys matter here
    assert len(ks) == 20 and ks == sorted(ks), ks  # 10 claim keys + 10 binding keys


def test_duplicate_entries_in_one_batch_never_abort_the_snapshot(client, seed, inv):
    """Same serial twice (different vendor) and one device with both protocols: the valid entries must still be ingested."""
    a = agent(client, inv, "a1")
    c = "c-dups"
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": "DUP-SAME-1", "vendor": "First", "binding": {"protocol": "tr069", "external_id": "dup-same", "connector_id": c}},
        {"canonical_serial": "DUP-SAME-1", "vendor": "Second", "binding": {"protocol": "tr069", "external_id": "dup-same", "connector_id": c}},
        {"canonical_serial": "DUP-BOTH-1", "vendor": "V", "binding": {"protocol": "tr069", "external_id": "both-cwmp", "connector_id": c}},
        {"canonical_serial": "DUP-BOTH-1", "vendor": "V", "binding": {"protocol": "tr369", "external_id": "both-usp", "connector_id": c}},
        {"canonical_serial": "DUP-OK-1", "vendor": "V", "binding": {"protocol": "tr069", "external_id": "ok-1", "connector_id": c}}]}
    r = client.post("/v1/edge/cpe-snapshots", headers=a, json=body)
    assert r.status_code == 202, r.text
    rows = {x["canonical_serial"]: x for x in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json()}
    assert {"DUP-SAME-1", "DUP-BOTH-1", "DUP-OK-1"} <= set(rows)
    assert len(rows["DUP-SAME-1"]["bindings"]) == 1 and len(rows["DUP-BOTH-1"]["bindings"]) == 2


def test_two_serials_claiming_the_same_binding_in_one_batch_are_both_ignored(client, seed, inv):
    a = agent(client, inv, "a1")
    c = "c-samebind"
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": "SAMEB-ONE-1", "binding": {"protocol": "tr069", "external_id": "shared-ext", "connector_id": c}},
        {"canonical_serial": "SAMEB-TWO-1", "binding": {"protocol": "tr069", "external_id": "shared-ext", "connector_id": c}},
        {"canonical_serial": "SAMEB-OK-1", "binding": {"protocol": "tr069", "external_id": "fine-ext", "connector_id": c}}]}
    r = client.post("/v1/edge/cpe-snapshots", headers=a, json=body)
    assert r.status_code == 202 and r.json()["conflicts"] == 2 and r.json()["cpes"] == 1, r.text
    serials = {x["canonical_serial"] for x in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json()}
    assert "SAMEB-OK-1" in serials and not ({"SAMEB-ONE-1", "SAMEB-TWO-1"} & serials)  # no CPE persisted without its binding


def test_a_binding_already_linked_to_another_serial_costs_only_that_claim(client, seed, inv):
    a = agent(client, inv, "a1")
    c = "c-linked"

    def post(cpes, obs=None):
        return client.post("/v1/edge/cpe-snapshots", headers=a, json={"edge_id": str(inv["a1"]["edge"]), "observed_at": obs or _now(), "cpes": cpes})

    mk = lambda serial, ext: {"canonical_serial": serial, "binding": {"protocol": "tr069", "external_id": ext, "connector_id": c}}  # noqa: E731
    assert post([mk("LINK-OWNER-1", "linked-ext")], _now(-5)).status_code == 202
    r = post([mk("LINK-THIEF-1", "linked-ext"), mk("LINK-FINE-1", "fine-linked")])
    assert r.status_code == 202 and r.json()["conflicts"] == 1 and r.json()["cpes"] == 1, r.text
    rows = {x["canonical_serial"]: x for x in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json()}
    assert "LINK-FINE-1" in rows and "LINK-THIEF-1" not in rows and rows["LINK-OWNER-1"]["bindings"][0]["external_id"] == "linked-ext"


def test_identical_repeated_claims_next_to_a_valid_entry_are_deduplicated(client, seed, inv):
    a = agent(client, inv, "a1")
    one = {"canonical_serial": "REP-ONE-1", "vendor": "A", "binding": {"protocol": "tr069", "external_id": "rep-ext", "connector_id": "c-rep"}}
    ok = {"canonical_serial": "REP-OK-1", "binding": {"protocol": "tr069", "external_id": "rep-ok", "connector_id": "c-rep"}}
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [one, {**one, "vendor": "B"}, ok]}
    r = client.post("/v1/edge/cpe-snapshots", headers=a, json=body)
    assert r.status_code == 202 and r.json() == {"status": "accepted", "cpes": 2, "skipped": 0, "conflicts": 0}, r.text


def test_one_device_over_two_protocols_makes_one_cpe_with_two_bindings_and_the_first_claim_names_it(client, seed, inv):
    a = agent(client, inv, "a1")
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": "MULTI-PROTO-1", "vendor": "FirstVendor", "binding": {"protocol": "tr069", "external_id": "mp-cwmp", "connector_id": "c-mp"}},
        {"canonical_serial": "MULTI-PROTO-1", "vendor": "SecondVendor", "binding": {"protocol": "tr369", "external_id": "mp-usp", "connector_id": "c-mp"}},
        {"canonical_serial": "MULTI-OTHER-1", "binding": {"protocol": "tr069", "external_id": "mp-other", "connector_id": "c-mp"}}]}
    r = client.post("/v1/edge/cpe-snapshots", headers=a, json=body)
    assert r.status_code == 202 and r.json()["conflicts"] == 0 and r.json()["cpes"] == 3, r.text
    rows = {x["canonical_serial"]: x for x in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json()}
    assert rows["MULTI-PROTO-1"]["vendor"] == "FirstVendor" and {b["protocol"] for b in rows["MULTI-PROTO-1"]["bindings"]} == {"tr069", "tr369"}
    assert "MULTI-OTHER-1" in rows


# ---- ONUs offline for at least X hours (backlog report) ----
def _age(migrated, seed, serial, down_hours=None, last_online_hours=None, observed_hours=None):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text(
            "UPDATE onus SET down_since = CASE WHEN CAST(:d AS float) IS NULL THEN NULL ELSE now() - CAST(:d AS float) * interval '1 hour' END, "
            "last_online_at = CASE WHEN CAST(:l AS float) IS NULL THEN NULL ELSE now() - CAST(:l AS float) * interval '1 hour' END, "
            "observed_at = CASE WHEN CAST(:o AS float) IS NULL THEN observed_at ELSE now() - CAST(:o AS float) * interval '1 hour' END "
            "WHERE serial = :s"), {"d": down_hours, "l": last_online_hours, "o": observed_hours, "s": serial})


def _offline_setup(client, seed, inv, migrated):
    body = snap(inv)
    body["onus"] = [
        {"serial": "OFF-LONG-0001", "pon_path": "0/1/0", "status": "offline", "rx_dbm": None},
        {"serial": "OFF-SHORT-001", "pon_path": "0/1/0", "status": "offline", "rx_dbm": None},
        {"serial": "OFF-LASTON-01", "pon_path": "0/1/1", "status": "los", "rx_dbm": None},
        {"serial": "OFF-UNKNOWN-1", "pon_path": "0/1/1", "status": "offline", "rx_dbm": None},
        {"serial": "OFF-ONLINE-01", "pon_path": "0/1/0", "status": "online", "rx_dbm": -20.0},
        {"serial": "=OFF-FORMULA-1", "pon_path": "0/1/0", "status": "offline", "rx_dbm": None},
    ]
    body["pons"] = [{"pon_path": "0/1/0", "status": "up", "complete": False}, {"pon_path": "0/1/1", "status": "up", "complete": False}]
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    _age(migrated, seed, "OFF-LONG-0001", down_hours=30, last_online_hours=31)
    _age(migrated, seed, "OFF-SHORT-001", down_hours=5, last_online_hours=6)
    _age(migrated, seed, "OFF-LASTON-01", down_hours=None, last_online_hours=50)
    _age(migrated, seed, "OFF-UNKNOWN-1", down_hours=None, last_online_hours=None)
    _age(migrated, seed, "=OFF-FORMULA-1", down_hours=26, last_online_hours=27)
    return hdr(client, "alice", seed, "A")


def test_offline_report_lists_long_outages_first_with_an_honest_basis(client, seed, inv, migrated):
    h = _offline_setup(client, seed, inv, migrated)
    r = client.get("/v1/onus/offline?min_hours=24", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    got = [(i["serial"], i["basis"]) for i in d["items"]]
    assert got == [("OFF-LASTON-01", "since_last_online"), ("OFF-LONG-0001", "transition_observed"), ("=OFF-FORMULA-1", "transition_observed")]
    assert d["excluded"]["stale"] == 0 and d["excluded"]["unknown_start"] >= 1 and d["count"] == 3 and d["truncated"] is False  # (other tests leave ONUs too)
    first = d["items"][0]
    assert first["offline_hours"] >= 49.9 and first["pon_path"] == "0/1/1" and first["status"] == "los" and first["freshness"] == "fresh"
    assert "customer" not in json.dumps(d).lower()              # no personal data: serial, OLT and PON only
    short = client.get("/v1/onus/offline?min_hours=1", headers=h).json()
    assert [i["serial"] for i in short["items"]][:2] == ["OFF-LASTON-01", "OFF-LONG-0001"] and "OFF-SHORT-001" in [i["serial"] for i in short["items"]]
    assert "OFF-ONLINE-01" not in [i["serial"] for i in short["items"]]
    only_pon = client.get("/v1/onus/offline?min_hours=1&pon_path=0/1/0", headers=h).json()
    assert {i["pon_path"] for i in only_pon["items"]} == {"0/1/0"}
    assert client.get("/v1/onus/offline?pon_path=0/1/0;drop", headers=h).status_code == 422
    assert client.get("/v1/onus/offline?min_hours=-1", headers=h).status_code == 422


def test_offline_report_leaves_out_stale_olt_data_unless_asked_and_is_tenant_isolated(client, seed, inv, migrated):
    h = _offline_setup(client, seed, inv, migrated)
    _age(migrated, seed, "OFF-LONG-0001", down_hours=30, last_online_hours=31, observed_hours=72)   # the OLT stopped being collected
    d = client.get("/v1/onus/offline?min_hours=24", headers=h).json()
    assert "OFF-LONG-0001" not in [i["serial"] for i in d["items"]] and d["excluded"]["stale"] == 1
    d2 = client.get("/v1/onus/offline?min_hours=24&include_stale=true", headers=h).json()
    row = next(i for i in d2["items"] if i["serial"] == "OFF-LONG-0001")
    assert row["freshness"] == "stale"
    assert client.get("/v1/onus/offline?min_hours=0", headers=hdr(client, "bob", seed, "B")).json()["items"] == []


def test_offline_report_csv_neutralises_formulas_and_carries_the_exclusions(client, seed, inv, migrated):
    h = _offline_setup(client, seed, inv, migrated)
    r = client.get("/v1/onus/offline?min_hours=24&format=csv", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert int(r.headers["X-Excluded-Unknown-Start"]) >= 1 and r.headers["X-Excluded-Stale"] == "0" and r.headers["X-Truncated"] == "false"
    lines = r.text.strip().splitlines()
    assert lines[0] == "serial,olt,pon_path,status,offline_since,offline_hours,basis,last_online_at,observed_at,freshness"
    assert len(lines) == 4 and any(l.startswith("'=OFF-FORMULA-1,") for l in lines)   # a leading = would run as a formula in a spreadsheet
