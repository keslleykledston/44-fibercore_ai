"""Profile Studio API (ADR-0040): import as an IMMUTABLE snapshot, clone to a draft, `If-Match`, compare, per-OLT dry run. Read and simulation only: nothing here writes to
equipment, opens a job or publishes an event."""
import copy
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import agent, hdr, snap

PROFILE = {
    "dba_type": "type3", "fixed_kbps": None, "assured_kbps": 1000, "maximum_kbps": 100000, "tconts": [{"index": 1, "dba_reference": "dba-lab-rev2"}],
    "gems": [{"gem_index": 1, "tcont_index": 1, "vlan": 200}], "customer_vlan": 200, "service_vlan": 200, "tagging": "tagged", "ethernet_ports": [1],
    "shaping_owner": "bng", "multicast": False, "description": "synthetic profile",
}
VENDOR, MODEL, FW = "huawei", "MA5800-X7", "R018"


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features"))
        c.execute(text("DELETE FROM profile_dry_runs"))
        c.execute(text("DELETE FROM profile_drafts"))
        c.execute(text("DELETE FROM olt_profile_snapshots"))
        c.execute(text("DELETE FROM olt_query_latest WHERE query_id = 'olt.profile.dba'"))
        c.execute(text("DELETE FROM device_capabilities WHERE operation = 'olt_profile_read'"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-PS-%'"))


def _on(migrated, tenant, value=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'profile_studio',:v) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = :v"),
                  {"t": tenant, "v": value})


def _certify(migrated, tenant, firmware=FW):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, verified_at, evidence_ref) "
                       "VALUES (:t,:v,:m,:f,'olt','olt_profile_read','supported','observed',now(),'synthetic test evidence')"), {"t": tenant, "v": VENDOR, "m": MODEL, "f": firmware})


def _trust(migrated, *snapshot_ids):
    """Stand-in for the supervised Edge reader (not delivered yet): the ONLY way a snapshot becomes authoritative is a read by the certified reader, never an import."""
    with migrated.begin() as c:
        for i in snapshot_ids:
            c.execute(text("UPDATE olt_profile_snapshots SET source = 'edge_read' WHERE id = :i"), {"i": i})


def _olt(client, inv, h, name, key="a1", **kw):
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, key), json=snap(inv, key, name=name, **kw))
    assert r.status_code == 202, r.text
    return next(o["id"] for o in client.get("/v1/olts?limit=1000", headers=h).json() if o["name"] == name)


def _import(client, h, olt, key="gpon-line-profile/42", settings=None, **kw):
    body = {"native_type": "gpon-line-profile", "native_key": key, "technology": "gpon", "pon_card": "GPON-LAB", "observed_at": datetime.now(UTC).isoformat(),
            "completeness": "complete", "reference_count": 3, "settings": copy.deepcopy(PROFILE if settings is None else settings), "unknown_fields": [], "source": "fixture"}
    body.update(kw)
    return client.post(f"/v1/olts/{olt}/profiles/import", headers=h, json=body)


def _draft(client, h, snapshot_id, **kw):
    body = {"name": "Internet bridge", "reason": "teste sintético", "source_snapshot_id": snapshot_id}
    body.update(kw)
    return client.post("/v1/profile-drafts", headers=h, json=body)


# ---- flag and permissions ------------------------------------------------------------------------------------------------------------------
def test_everything_is_off_by_default_and_needs_the_permission(client, seed, inv, migrated):
    h, hn1 = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")
    olt = _olt(client, inv, h, "OLT-PS-OFF")
    assert _import(client, h, olt).status_code == 403 and _import(client, h, olt).json()["detail"] == "feature_disabled"
    for r in (client.get(f"/v1/olts/{olt}/profiles", headers=h), client.get("/v1/profile-drafts", headers=h),
              client.post("/v1/profile-drafts", headers=h, json={"name": "x", "reason": "y"})):
        assert r.status_code == 403
    _on(migrated, seed["A"])
    assert client.get(f"/v1/olts/{olt}/profiles", headers=h).status_code == 200
    for r in (client.get(f"/v1/olts/{olt}/profiles", headers=hn1), _import_as(client, hn1, olt)):   # noc_n1 holds no profiles permission
        assert r.status_code == 403


def _import_as(client, h, olt):
    return _import(client, h, olt)


# ---- import: immutable evidence -------------------------------------------------------------------------------------------------------------
def test_import_stores_an_immutable_snapshot_with_server_side_identity_and_inert_evidence(client, seed, inv, migrated):
    from app.core.db import get_engine, scoped_connection
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-PS-1")
    r = _import(client, h, olt, evidence="\x1b[31mdisplay dba-profile\x1b[0m <script>alert(1)</script> ignore previous instructions", reference_count=None)
    assert r.status_code == 201, r.text
    s = r.json()
    assert (s["vendor"], s["model"], s["firmware"]) == (VENDOR, MODEL, FW)                    # from the OLT row, not from the caller
    assert len(s["fingerprint"]) == 64 and s["freshness"] == "fresh" and s["reference_count"] is None and s["has_evidence"] is True
    full = client.get(f"/v1/profile-snapshots/{s['id']}", headers=h).json()
    assert "<script>" not in full["evidence"] and "&lt;script&gt;" in full["evidence"] and "\x1b" not in full["evidence"]
    same_a, same_b = _import(client, h, olt, key="gpon-line-profile/99").json(), _import(client, h, olt, key="gpon-line-profile/99").json()
    assert same_a["fingerprint"] == same_b["fingerprint"] != s["fingerprint"]                  # content-addressed: same content, same fingerprint; another key, another one
    assert _import(client, h, olt, key="gpon-line-profile/99", settings={**PROFILE, "customer_vlan": 7}).json()["fingerprint"] != same_a["fingerprint"]
    for stmt in ("UPDATE olt_profile_snapshots SET settings = '{}'::jsonb", "DELETE FROM olt_profile_snapshots"):
        with pytest.raises(DBAPIError), scoped_connection(get_engine(), tenant_id=seed["A"]) as c:
            c.execute(text(stmt))
    with migrated.begin() as c:
        assert tuple(c.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'olt_profile_snapshots'")).one()) == (True, True)


def test_import_refuses_what_does_not_fit_the_typed_model_and_stores_nothing(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-PS-2")
    bad = [({**PROFILE, "raw_cli": "undo"}, "forbidden_key"), ({**PROFILE, "made_up": 1}, "unknown_field"), ({**PROFILE, "customer_vlan": 9999}, "range"),
           ({**PROFILE, "assured_kbps": 9, "maximum_kbps": 5}, "qos_min_exceeds_max")]
    for settings, code in bad:
        r = _import(client, h, olt, settings=settings)
        assert r.status_code == 422 and code in json.dumps(r.json()), (code, r.text)
    assert _import(client, h, olt, unknown_fields=["customer_vlan"]).status_code == 422       # named unknown AND present
    assert _import(client, h, olt, unknown_fields=["nope"]).status_code == 422
    assert _import(client, h, olt, source="edge_read").status_code == 422                     # reserved for the supervised Edge reader
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert _import(client, h, olt, observed_at=future).status_code == 422
    assert _import(client, h, olt, native_key="bad key!").status_code == 422
    assert client.get(f"/v1/olts/{olt}/profiles", headers=h).json()["items"] == []


def test_listing_shows_the_newest_per_profile_with_the_freshness_it_has_now(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-PS-3")
    old = (datetime.now(UTC) - timedelta(hours=7)).isoformat()
    assert _import(client, h, olt, key="gpon-line-profile/7", observed_at=old).status_code == 201
    assert _import(client, h, olt, key="gpon-line-profile/8").status_code == 201
    body = client.get(f"/v1/olts/{olt}/profiles", headers=h).json()
    fr = {i["native_key"]: i["freshness"] for i in body["items"]}
    assert fr == {"gpon-line-profile/7": "stale", "gpon-line-profile/8": "fresh"} and body["driver_read_certified"] is False
    _certify(migrated, seed["A"])
    assert client.get(f"/v1/olts/{olt}/profiles", headers=h).json()["driver_read_certified"] is True


# ---- tenancy --------------------------------------------------------------------------------------------------------------------------------
def test_another_tenant_sees_and_uses_nothing(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    _on(migrated, seed["B"])
    ha, hb = hdr(client, "alice", seed, "A"), hdr(client, "bob", seed, "B")
    olt = _olt(client, inv, ha, "OLT-PS-4")
    snap_id = _import(client, ha, olt).json()["id"]
    draft_id = _draft(client, ha, snap_id).json()["id"]
    assert client.get(f"/v1/olts/{olt}/profiles", headers=hb).status_code == 404
    assert client.get(f"/v1/profile-snapshots/{snap_id}", headers=hb).status_code == 404
    assert client.get(f"/v1/profile-drafts/{draft_id}", headers=hb).status_code == 404
    assert _import(client, hb, olt).status_code == 404
    assert _draft(client, hb, snap_id).status_code == 404
    assert client.get("/v1/profile-drafts", headers=hb).json()["items"] == []
    mine = _olt(client, inv, hb, "OLT-PS-4B", key="b1")
    assert client.post(f"/v1/profile-drafts/{draft_id}/dry-run", headers=hb, json={"target_olt_ids": [mine]}).status_code == 404
    assert client.post("/v1/profile-drafts", headers=ha, json={"name": "x", "reason": "y", "technology": "gpon", "vendor": VENDOR, "model": MODEL, "firmware": FW,
                                                               "pon_card": "C", "target_olt_ids": [mine]}).status_code == 404   # B's OLT is not A's target


# ---- drafts and If-Match --------------------------------------------------------------------------------------------------------------------
def test_a_draft_is_a_clone_with_etag_and_the_snapshot_never_changes(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-PS-5")
    s = _import(client, h, olt).json()
    r = _draft(client, h, s["id"], target_olt_ids=[olt])
    assert r.status_code == 201 and r.headers["ETag"] == '"1"'
    d = r.json()
    assert d["scope"] == {"technology": "gpon", "vendor": VENDOR, "model": MODEL, "firmware": FW, "pon_card": "GPON-LAB"} and d["desired"] == s["settings"]
    assert _draft(client, h, s["id"], vendor="zte").status_code == 422                          # the scope comes from the snapshot
    assert client.post("/v1/profile-drafts", headers=h, json={"name": "x", "reason": "y"}).status_code == 422   # no source and no scope
    assert _draft(client, h, s["id"], desired={**PROFILE, "shell": "x"}).status_code == 422
    edit = {**d["desired"], "customer_vlan": 300}
    path = f"/v1/profile-drafts/{d['id']}"
    assert client.patch(path, headers=h, json={"desired": edit}).status_code == 428           # If-Match is required
    assert client.patch(path, headers={**h, "If-Match": '"9"'}, json={"desired": edit}).status_code == 412
    ok = client.patch(path, headers={**h, "If-Match": '"1"'}, json={"desired": edit, "reason": "VLAN 300"})
    assert ok.status_code == 200 and ok.headers["ETag"] == '"2"' and ok.json()["desired"]["customer_vlan"] == 300
    assert client.patch(path, headers={**h, "If-Match": '"1"'}, json={"reason": "stale editor"}).status_code == 412   # a stale editor never overwrites
    assert client.patch(path, headers={**h, "If-Match": '"2"'}, json={"vendor_extensions": {"burst": 5}}).status_code == 422   # no approved extension schema yet
    assert client.patch(path, headers={**h, "If-Match": '"2"'}, json={"vendor_extensions": {"shell": "x"}}).status_code == 422
    assert client.patch(path, headers={**h, "If-Match": '"2"'}, json={}).status_code == 422
    assert client.get(f"/v1/profile-snapshots/{s['id']}", headers=h).json()["settings"] == s["settings"]   # the evidence is untouched
    assert client.get(path, headers=h).headers["ETag"] == '"2"'


# ---- compare --------------------------------------------------------------------------------------------------------------------------------
def test_compare_is_semantic_and_never_calls_an_unproven_profile_equivalent(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-PS-6")
    s = _import(client, h, olt).json()
    d = _draft(client, h, s["id"]).json()
    cmp_ = lambda sid: client.post(f"/v1/profile-drafts/{d['id']}/compare", headers=h, json={"snapshot_id": sid}).json()  # noqa: E731
    c = cmp_(s["id"])
    assert c["driver_read_certified"] is False and "read_not_certified" in c["blockers"] and c["equivalent"] is False   # no certified read: nothing is proven
    assert set(c["diff"].values()) == {"UNSUPPORTED"}                                         # every typed field is beyond what a non-certified driver may claim
    _certify(migrated, seed["A"])
    c = cmp_(s["id"])
    assert c["blockers"] == ["snapshot_not_authoritative"] and c["equivalent"] is False and set(c["diff"].values()) == {"EQUAL"}   # a manual import proves nothing
    _trust(migrated, s["id"])
    c = cmp_(s["id"])
    assert c["blockers"] == [] and c["equivalent"] is True and set(c["diff"].values()) == {"EQUAL"} and client.get(f"/v1/profile-snapshots/{s['id']}", headers=h).json()["authoritative"]
    partial = _import(client, h, olt, key="gpon-line-profile/9", completeness="partial", unknown_fields=["multicast"],
                      settings={k: v for k, v in PROFILE.items() if k != "multicast"}).json()
    c2 = cmp_(partial["id"])
    assert c2["diff"]["multicast"] == "NOT_OBSERVABLE" and c2["equivalent"] is False and "incomplete_observation" in c2["blockers"]
    other = _import(client, h, olt, key="gpon-line-profile/10", settings={**PROFILE, "tagging": "translation"}).json()
    c3 = cmp_(other["id"])
    assert c3["diff"]["tagging"] == "CHANGE" and c3["equivalent"] is False and c3["counts"]["CHANGE"] == 1
    old = _import(client, h, olt, key="gpon-line-profile/11", observed_at=(datetime.now(UTC) - timedelta(hours=8)).isoformat()).json()
    assert "stale_or_unknown_snapshot" in cmp_(old["id"])["blockers"] and cmp_(old["id"])["equivalent"] is False
    assert client.post(f"/v1/profile-drafts/{d['id']}/compare", headers=h, json={"snapshot_id": "00000000-0000-4000-8000-000000000000"}).status_code == 404


# ---- dry run --------------------------------------------------------------------------------------------------------------------------------
def test_dry_run_is_per_olt_independent_reproducible_and_writes_nothing(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    _certify(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    a, b = _olt(client, inv, h, "OLT-PS-A"), _olt(client, inv, h, "OLT-PS-B")
    c = _olt(client, inv, h, "OLT-PS-C", firmware="R019")                                  # another firmware: out of the draft's scope
    src = _import(client, h, a).json()
    _trust(migrated, src["id"])
    assert _import(client, h, b, key="local-77", settings={**PROFILE, "customer_vlan": 999}).status_code == 201   # B has only a DIFFERENT profile
    d = _draft(client, h, src["id"], target_olt_ids=[a, b, c]).json()
    with migrated.begin() as cn:
        before = cn.execute(text("SELECT (SELECT count(*) FROM jobs), (SELECT count(*) FROM events_outbox), (SELECT count(*) FROM incidents)")).one()
    r = client.post(f"/v1/profile-drafts/{d['id']}/dry-run", headers=h, json={})
    assert r.status_code == 201, r.text
    run = r.json()
    plans = {p["olt_id"]: p for p in run["plans"]}
    assert plans[a]["strategy"] == "reuse_exact" and plans[a]["changed_fields"] == [] and plans[a]["reference_count"] == 3
    assert plans[b]["strategy"] == "clone_new_revision" and plans[b]["changed_fields"] == ["customer_vlan"]
    assert plans[c]["strategy"] == "blocked" and plans[c]["reason"] == "target_out_of_scope" and plans[c]["diff"] == {}
    assert len({p["plan_hash"] for p in run["plans"]}) == 3 and all(p["writes"] == 0 for p in run["plans"])   # independent hashes, zero writes
    assert run["writes"] == 0 and run["executable"] is False and run["issues"] == []
    with migrated.begin() as cn:
        after = cn.execute(text("SELECT (SELECT count(*) FROM jobs), (SELECT count(*) FROM events_outbox), (SELECT count(*) FROM incidents)")).one()
    assert after == before                                                                  # no job, no event, no incident
    got = client.get(f"/v1/profile-dry-runs/{run['run_id']}", headers=h).json()
    assert got["reproducible"] is True and got["expired"] is False and got["plans"] == run["plans"]
    with migrated.begin() as cn:                                                            # the approval bound to this hash stops applying when it expires
        cn.execute(text("UPDATE profile_dry_runs SET expires_at = now() - interval '1 minute' WHERE id = :i"), {"i": run["run_id"]})
    assert client.get(f"/v1/profile-dry-runs/{run['run_id']}", headers=h).json()["expired"] is True
    # editing the draft changes the intent revision, so the same OLT gets another hash
    ok = client.patch(f"/v1/profile-drafts/{d['id']}", headers={**h, "If-Match": '"1"'}, json={"reason": "outra revisão"})
    assert ok.status_code == 200
    again = {p["olt_id"]: p for p in client.post(f"/v1/profile-drafts/{d['id']}/dry-run", headers=h, json={}).json()["plans"]}
    assert again[a]["plan_hash"] != plans[a]["plan_hash"] and again[a]["strategy"] == "reuse_exact"


def test_without_a_certified_driver_read_nothing_is_reused_or_cloned(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    a = _olt(client, inv, h, "OLT-PS-U")
    src = _import(client, h, a).json()
    d = _draft(client, h, src["id"], target_olt_ids=[a]).json()
    plan = client.post(f"/v1/profile-drafts/{d['id']}/dry-run", headers=h, json={}).json()["plans"][0]
    assert plan["strategy"] == "blocked" and plan["reason"] in ("invalid_draft", "read_not_certified")
    assert client.post(f"/v1/profile-drafts/{d['id']}/dry-run", headers=h, json={"target_olt_ids": []}).status_code == 422
    nothing = client.post("/v1/profile-drafts", headers=h, json={"name": "n", "reason": "r", "technology": "gpon", "vendor": VENDOR, "model": MODEL, "firmware": FW,
                                                                 "pon_card": "C", "desired": {"customer_vlan": 100}}).json()
    assert client.post(f"/v1/profile-drafts/{nothing['id']}/dry-run", headers=h, json={}).status_code == 422   # no target at all


def test_a_stale_or_changed_source_never_reuses(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    _certify(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    a = _olt(client, inv, h, "OLT-PS-S")
    first = _import(client, h, a).json()
    _trust(migrated, first["id"])
    d = _draft(client, h, first["id"], target_olt_ids=[a]).json()
    # the OLT's profile CHANGED after the draft was cloned from it (same native key, newer snapshot with another content)
    newer = _import(client, h, a, settings={**PROFILE, "customer_vlan": 400})
    assert newer.status_code == 201
    _trust(migrated, newer.json()["id"])
    plan = client.post(f"/v1/profile-drafts/{d['id']}/dry-run", headers=h, json={"requested": "reuse_exact"}).json()["plans"][0]
    assert plan["strategy"] == "blocked" and plan["reason"] == "source_changed"
    auto = client.post(f"/v1/profile-drafts/{d['id']}/dry-run", headers=h, json={}).json()["plans"][0]
    assert auto["strategy"] in ("clone_new_revision", "blocked") and auto["strategy"] != "reuse_exact"
    mig = client.post(f"/v1/profile-drafts/{d['id']}/dry-run", headers=h, json={"requested": "plan_migration"}).json()["plans"][0]
    assert mig["strategy"] in ("plan_migration", "blocked")                                  # never executed: this API has no execution at all


def test_a_manual_import_is_never_a_basis_to_reuse_and_an_old_certification_stops_counting(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    _certify(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    a = _olt(client, inv, h, "OLT-PS-M")
    src = _import(client, h, a).json()                                                      # a perfectly equal, fresh, complete MANUAL import
    d = _draft(client, h, src["id"], target_olt_ids=[a]).json()
    path = f"/v1/profile-drafts/{d['id']}/dry-run"
    reuse = client.post(path, headers=h, json={"requested": "reuse_exact"}).json()["plans"][0]
    assert reuse["strategy"] == "blocked" and reuse["reason"] == "snapshot_not_authoritative"
    for req in ("adopt_reference", "plan_migration"):
        assert client.post(path, headers=h, json={"requested": req}).json()["plans"][0]["reason"] == "snapshot_not_authoritative"
    assert client.post(path, headers=h, json={}).json()["plans"][0]["strategy"] == "clone_new_revision"   # a clone is still possible: it writes nothing and needs no proof
    _trust(migrated, src["id"])
    assert client.post(path, headers=h, json={"requested": "reuse_exact"}).json()["plans"][0]["strategy"] == "reuse_exact"
    with migrated.begin() as c:                                                             # the certification was verified 91 days ago: it must be verified again
        c.execute(text("UPDATE device_capabilities SET verified_at = now() - interval '91 days' WHERE operation = 'olt_profile_read'"))
    assert client.get(f"/v1/olts/{a}/profiles", headers=h).json()["driver_read_certified"] is False
    old = client.post(path, headers=h, json={"requested": "reuse_exact"}).json()["plans"][0]
    assert old["strategy"] == "blocked" and old["reason"] in ("invalid_draft", "read_not_certified")
    with migrated.begin() as c:                                                             # a verification dated in the future is not a verification
        c.execute(text("UPDATE device_capabilities SET verified_at = now() + interval '30 days' WHERE operation = 'olt_profile_read'"))
    assert client.get(f"/v1/olts/{a}/profiles", headers=h).json()["driver_read_certified"] is False
    with migrated.begin() as c:                                                             # and a few minutes of clock skew are tolerated
        c.execute(text("UPDATE device_capabilities SET verified_at = now() + interval '2 minutes' WHERE operation = 'olt_profile_read'"))
    assert client.get(f"/v1/olts/{a}/profiles", headers=h).json()["driver_read_certified"] is True


# ---- sync from the Edge's supervised reads ---------------------------------------------------------------------------------------------------
def _store_dba_read(migrated, tenant, olt, rows, age=timedelta(0)):
    from app.core import olt_cache
    from app.core.db import get_engine, scoped_connection
    with scoped_connection(get_engine(), tenant_id=tenant) as c:
        epoch = c.execute(text("SELECT owner_epoch FROM olts WHERE id = :i"), {"i": olt}).scalar()
        olt_cache.store_latest(c, tenant, __import__("uuid").UUID(str(olt)), "olt.profile.dba", "", {"profiles": rows}, epoch, datetime.now(UTC))
    if age:
        with migrated.begin() as c:
            c.execute(text("UPDATE olt_query_latest SET asked_at = asked_at - make_interval(secs => :s) WHERE olt_id = :i"), {"s": age.total_seconds(), "i": olt})


def test_sync_turns_the_dba_read_into_authoritative_snapshots_and_is_idempotent(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    olt = _olt(client, inv, h, "OLT-PS-SYNC")
    assert client.post(f"/v1/olts/{olt}/profiles/sync", headers=h).status_code == 409           # nothing was read yet
    rows = [{"id": 0, "type": 3, "compensation": False, "fixed_kbps": 0, "assured_kbps": 8192, "maximum_kbps": 20480, "binding_times": 0},
            {"id": 1, "type": 1, "compensation": False, "fixed_kbps": 5120, "assured_kbps": 0, "maximum_kbps": 0, "binding_times": 40},
            {"id": 2, "type": 3, "compensation": False, "fixed_kbps": 0, "assured_kbps": 9000, "maximum_kbps": 1000, "binding_times": 1}]   # assured above maximum: not storable
    _store_dba_read(migrated, seed["A"], olt, rows)
    r = client.post(f"/v1/olts/{olt}/profiles/sync", headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["created"], b["unchanged"]) == (2, 0) and b["skipped"] == [{"native_key": "2", "issues": [{"field": "assured_kbps", "code": "qos_min_exceeds_max"}]}]
    assert client.post(f"/v1/olts/{olt}/profiles/sync", headers=h).json()["unchanged"] == 2    # same read, same fingerprints: nothing new
    items = {x["native_key"]: x for x in client.get(f"/v1/olts/{olt}/profiles", headers=h).json()["items"]}
    assert set(items) == {"0", "1"} and items["0"]["source"] == "edge_read" and items["0"]["authoritative"] is True and items["0"]["completeness"] == "partial"
    snap0 = client.get(f"/v1/profile-snapshots/{items['0']['id']}", headers=h).json()
    assert snap0["settings"]["dba_type"] == "type3" and snap0["settings"]["maximum_kbps"] == 20480 and snap0["settings"]["fixed_kbps"] is None
    assert "tagging" in snap0["unknown_fields"] and "assured_kbps" not in snap0["unknown_fields"]   # what the read does not state is named, not invented
    assert client.get(f"/v1/profile-snapshots/{items['1']['id']}", headers=h).json()["settings"]["maximum_kbps"] is None   # type 1 has no maximum
    # the read changes -> a NEW snapshot for that profile only
    rows[1] = {**rows[1], "fixed_kbps": 10240}
    _store_dba_read(migrated, seed["A"], olt, rows)
    again = client.post(f"/v1/olts/{olt}/profiles/sync", headers=h).json()
    assert (again["created"], again["unchanged"]) == (1, 1)
    # profile 1 disappears from the next complete read: it is not kept as current -> a newer snapshot that states nothing (unknown, no settings)
    _store_dba_read(migrated, seed["A"], olt, rows[:1])
    gone = client.post(f"/v1/olts/{olt}/profiles/sync", headers=h).json()
    assert (gone["created"], gone["unchanged"], gone["absent"]) == (0, 1, 1)
    items = {x["native_key"]: x for x in client.get(f"/v1/olts/{olt}/profiles", headers=h).json()["items"]}
    assert items["1"]["completeness"] == "unknown" and items["1"]["freshness"] == "unknown" and items["0"]["completeness"] == "partial"
    assert client.get(f"/v1/profile-snapshots/{items['1']['id']}", headers=h).json()["settings"] == {}
    assert client.post(f"/v1/olts/{olt}/profiles/sync", headers=h).json()["absent"] == 0      # idempotent: the absence is recorded once


def test_sync_refuses_an_old_read_a_missing_permission_and_the_flag_off(client, seed, inv, migrated):
    h, hn = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")
    olt = _olt(client, inv, h, "OLT-PS-SYNC2")
    assert client.post(f"/v1/olts/{olt}/profiles/sync", headers=h).status_code == 403            # flag off
    _on(migrated, seed["A"])
    _store_dba_read(migrated, seed["A"], olt, [{"id": 0, "type": 4, "compensation": False, "fixed_kbps": 0, "assured_kbps": 0, "maximum_kbps": 1000, "binding_times": 0}],
                    age=timedelta(hours=25))
    r = client.post(f"/v1/olts/{olt}/profiles/sync", headers=h)
    assert r.status_code == 409 and "read_too_old" in r.text
    assert client.post(f"/v1/olts/{olt}/profiles/sync", headers=hn).status_code == 403            # no profiles:import
    assert client.get(f"/v1/olts/{olt}/profiles", headers=h).json()["items"] == []
    # a LATE delivery (Codex r2): the answer reached the Cloud just now (observed_at = now) but the QUESTION is 25 h old -> still refused, nothing stored
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert c.execute(text("SELECT observed_at > now() - interval '1 minute' AND asked_at < now() - interval '24 hours' FROM olt_query_latest WHERE olt_id = :i"), {"i": olt}).scalar() is True
    assert client.post(f"/v1/olts/{olt}/profiles/sync", headers=h).status_code == 409
