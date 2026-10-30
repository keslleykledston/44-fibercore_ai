"""Authorizing a bench maneuver through the API (ADR-0031 2(e); owner decision 2026-10-30). The maneuver's other conditions (ADR-0030) are exercised in
test_jobs_bench; here: who may authorize what, the limits of the record, the independence of the authorizer, and that the writer is the SQL function."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import bench, settings
from app.core.security import ROLE_PERMISSIONS, hash_secret
from tests.conftest import hdr
from tests.test_jobs_bench import _bench, _cleanup, _cpe, _flag, _preview  # noqa: F401  (the autouse cleanup fixture comes along)

PW = "correct horse battery"


def _member(migrated, seed, role):
    email = f"ba{uuid4().hex[:8]}@example.com"
    with migrated.begin() as c:
        uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:e,:h) RETURNING id"), {"e": email, "h": hash_secret(PW)}).scalar()
        c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": seed["A"], "u": uid, "r": role})
    return {"email": email, "id": uid}


def _h(client, seed, who):
    r = client.post("/v1/auth/token", json={"email": who["email"], "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Workspace-ID": str(seed["A"])}


def _auth(client, h, cpe, op="reboot_cpe", params=None, minutes=30):
    return client.post("/v1/bench/authorizations", headers=h, json={"cpe_id": str(cpe), "operation": op, "params": params or {}, "minutes": minutes})


@pytest.fixture
def lab(client, seed, inv, migrated):
    """Bench target + observed entry, tenant flag ON, and NO authorization yet (the API gives it)."""
    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, authorization=False)
    with migrated.begin() as c:
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, verified_at, evidence_ref) "
                       "SELECT tenant_id, vendor, model, firmware, protocol, 'set_wifi_ssid', status, certification, verified_at, evidence_ref FROM device_capabilities "
                       "WHERE operation = 'reboot_cpe'"))
    return cpe


def test_the_catalog_the_python_table_and_the_sql_table_agree(migrated):
    holders = {r for r, p in ROLE_PERMISSIONS.items() if "bench:authorize" in p}
    assert holders == {"noc_n2", "engineer", "isp_admin"}          # from the operator up; no reader role, no access_manager, no auditor
    with migrated.connect() as c:
        rows = c.execute(text("SELECT role, operation FROM rbac_bench_authorizers")).all()
    assert {(r.role, r.operation) for r in rows} == {(r, o) for r, ops in bench.BENCH_AUTHORIZERS.items() for o in ops}
    assert set(bench.BENCH_AUTHORIZERS) == holders and all(ops <= set(bench.BENCH_OPS) for ops in bench.BENCH_AUTHORIZERS.values())


def test_who_may_authorize_what(client, seed, migrated, lab):
    cpe = lab
    for role in ("support", "noc_n1", "auditor", "access_manager"):
        assert _auth(client, _h(client, seed, _member(migrated, seed, role)), cpe).status_code in (401, 403), role   # (access_manager also needs MFA)
    op = _h(client, seed, _member(migrated, seed, "noc_n2"))
    r = _auth(client, op, cpe)
    assert r.status_code == 201, r.text
    # the operator covers the two CPE operations only; the OLT-side maneuvers are for the engineering roles
    for o in ("onu_reset", "onu_deactivate"):
        x = _auth(client, op, cpe, o)
        assert (x.status_code, x.json()["detail"]) == (403, "role_cannot_authorize"), o
    eng = _h(client, seed, _member(migrated, seed, "engineer"))
    x = _auth(client, eng, cpe, "onu_reset")
    assert x.status_code == 201, x.text                                                           # allowed by role; the engine's other conditions come later


def test_the_record_is_short_single_and_marked_as_api(client, seed, migrated, lab):
    cpe = lab
    who = _member(migrated, seed, "noc_n2")
    h = _h(client, seed, who)
    r = _auth(client, h, cpe, minutes=30)
    assert r.status_code == 201
    with migrated.connect() as c:
        a = c.execute(text("SELECT authorized_via, authorized_by_user_id, first_run, state, window_end - window_start AS w, params_hash FROM bench_authorizations")).one()
    assert (a.authorized_via, a.authorized_by_user_id, a.first_run, a.state) == ("api", who["id"], False, "open")
    assert timedelta(minutes=29) < a.w <= timedelta(minutes=30) and a.params_hash == bench.params_hash({})
    again = _auth(client, h, cpe)                                         # one live API authorization per target and operation
    assert (again.status_code, again.json()["detail"]) == (409, "authorization_already_open")
    for minutes in (4, 121):
        assert _auth(client, h, cpe, minutes=minutes).status_code == 422
    assert _auth(client, h, cpe, "set_wifi_ssid", {"ssid": "MeuWifi"}).status_code == 422
    assert _auth(client, h, cpe, "provision_onu").status_code == 422
    assert _auth(client, h, cpe, "reboot_cpe", {"x": 1}).status_code == 422
    with migrated.connect() as c:
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'bench.authorize' AND actor_id = :u"), {"u": who["id"]}).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM events_outbox WHERE event_type = 'bench.authorized'")).scalar_one() >= 1


def test_an_expired_api_authorization_does_not_block_a_new_one(client, seed, migrated, lab):
    h = _h(client, seed, _member(migrated, seed, "engineer"))
    assert _auth(client, h, lab).status_code == 201
    with migrated.begin() as c:
        c.execute(text("UPDATE bench_authorizations SET window_start = now() - interval '2 hours', window_end = now() - interval '1 minute'"))
    assert _auth(client, h, lab).status_code == 201
    with migrated.connect() as c:
        assert sorted(c.execute(text("SELECT state FROM bench_authorizations")).scalars().all()) == ["open", "revoked"]


def test_the_other_conditions_are_still_required(client, seed, inv, migrated, lab):
    cpe = lab
    h = _h(client, seed, _member(migrated, seed, "noc_n2"))
    other = _cpe(client, inv, seed, serial="BNCH-CPE-0002", ext="bench-ext-0002")             # exists, is NOT a bench target
    x = _auth(client, h, other)
    assert (x.status_code, x.json()["detail"]) == (409, "target_not_bench")
    with migrated.begin() as c:
        c.execute(text("UPDATE bench_targets SET write_locked = true, lock_reason = 'teste' WHERE cpe_id = :c"), {"c": cpe})
    x = _auth(client, h, cpe)
    assert (x.status_code, x.json()["detail"]) == (409, "target_write_locked")
    with migrated.begin() as c:
        c.execute(text("UPDATE bench_targets SET write_locked = false, lock_reason = NULL WHERE cpe_id = :c"), {"c": cpe})
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE feature = 'bench_writes'"))
    x = _auth(client, h, cpe)
    assert (x.status_code, x.json()["detail"]) == (409, "bench_writes_disabled")
    assert _auth(client, h, uuid4()).status_code == 409                                           # an unknown target is "not a bench target"


def test_the_authorizer_can_neither_request_nor_approve_the_job_they_authorized(client, seed, migrated, lab):
    cpe = lab
    alice = hdr(client, "alice", seed, "A")                                                       # isp_admin: requests (and may approve a bench job)
    authorizer = _member(migrated, seed, "isp_admin")                                              # holds jobs:request and jobs:approve too
    ah = _h(client, seed, authorizer)
    # 1) the authorizer is the requester: the job cannot even be submitted on that authorization
    assert _auth(client, ah, cpe).status_code == 201
    jid = _preview(client, ah, cpe).json()["id"]
    r = client.post(f"/v1/jobs/{jid}/submit", headers=ah)
    assert (r.status_code, r.json()["detail"]) == (409, "authorizer_not_independent")
    # 2) someone else requests, the authorizer would approve: refused, and the authorization stays unspent
    jid2 = _preview(client, alice, cpe).json()["id"]
    assert client.post(f"/v1/jobs/{jid2}/submit", headers=alice).json()["status"] == "PENDING_APPROVAL"
    r = client.post(f"/v1/jobs/{jid2}/approve", headers=ah)
    assert (r.status_code, r.json()["detail"]) == (409, "authorizer_not_independent")
    with migrated.connect() as c:
        assert c.execute(text("SELECT state FROM bench_authorizations")).scalar() == "open"
    # 3) requester and approver are both someone else: it works, the authorization is spent with the approval
    done = client.post(f"/v1/jobs/{jid2}/approve", headers=alice)    # alice requested it and may approve it (bench dispensation, owner decision)
    assert done.status_code == 200 and done.json()["status"] == "APPROVED", done.text
    with migrated.connect() as c:
        assert c.execute(text("SELECT state FROM bench_authorizations")).scalar() == "consumed"


def test_revoking(client, seed, migrated, lab):
    cpe = lab
    op = _h(client, seed, _member(migrated, seed, "noc_n2"))
    eng = _h(client, seed, _member(migrated, seed, "engineer"))
    aid = _auth(client, op, cpe).json()["id"]
    assert client.delete(f"/v1/bench/authorizations/{aid}", headers=_h(client, seed, _member(migrated, seed, "noc_n1"))).status_code == 403
    assert client.delete(f"/v1/bench/authorizations/{aid}", headers=eng).status_code == 200          # any authorizing role may withdraw it
    assert client.delete(f"/v1/bench/authorizations/{aid}", headers=eng).json()["detail"] == "authorization_not_open"
    alice = hdr(client, "alice", seed, "A")
    jid = _preview(client, alice, cpe).json()["id"]
    r = client.post(f"/v1/jobs/{jid}/submit", headers=alice)
    assert (r.status_code, r.json()["detail"]) == (409, "authorization_missing")                      # a withdrawn authorization opens nothing
    assert client.delete(f"/v1/bench/authorizations/{uuid4()}", headers=eng).status_code == 404
    assert client.delete(f"/v1/bench/authorizations/{aid}", headers=hdr(client, "bob", seed, "B")).status_code in (403, 404)


def test_the_owner_cli_path_is_untouched_and_not_subject_to_the_independence_rule(client, seed, inv, migrated, lab):
    cpe = lab
    with migrated.begin() as c:   # what bench-authorize records: via owner_cli, no person attached
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by) "
                       "VALUES (:t,'reboot_cpe',:c,:h,now(),now() + interval '30 minutes','responsavel')"), {"t": str(seed["A"]), "c": cpe, "h": bench.params_hash({})})
    with migrated.connect() as c:
        assert c.execute(text("SELECT authorized_via, authorized_by_user_id FROM bench_authorizations")).one() == ("owner_cli", None)
    alice = hdr(client, "alice", seed, "A")
    jid = _preview(client, alice, cpe).json()["id"]
    assert client.post(f"/v1/jobs/{jid}/submit", headers=alice).json()["status"] == "PENDING_APPROVAL"
    assert client.post(f"/v1/jobs/{jid}/approve", headers=alice).json()["status"] == "APPROVED"
    aid = None
    with migrated.connect() as c:
        aid = c.execute(text("SELECT id FROM bench_authorizations")).scalar()
    r = client.delete(f"/v1/bench/authorizations/{aid}", headers=_h(client, seed, _member(migrated, seed, "engineer")))
    assert r.status_code in (403, 409)      # consumed / owner-made: not the API's to withdraw


def test_the_writer_is_the_sql_function_and_the_database_keeps_the_limits(client, seed, migrated, lab):
    cpe = lab
    who = _member(migrated, seed, "engineer")
    # the application's normal role can neither execute the functions nor insert/alter an authorization, with or without forged session settings
    for stmt in ("SELECT app_bench_authorize(:u, :t, :c, 'reboot_cpe', repeat('a', 64), 30)", "SELECT app_bench_revoke(:u, :t, :c)",
                 "INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by, authorized_via, authorized_by_user_id) "
                 "VALUES (:t,'reboot_cpe',:c,repeat('a',64),now(),now() + interval '30 minutes','x','api',:u)"):
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text("SET LOCAL ROLE fibercore_app"))
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(stmt), {"u": who["id"], "t": str(seed["A"]), "c": cpe})
    for cols, vals in (("first_run, authorized_via, authorized_by_user_id", "true, 'api', :u"), ("authorized_via", "'api'"),
                       ("authorized_via, authorized_by_user_id", "'owner_cli', :u")):
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text(f"INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by, {cols}) "  # noqa: S608
                           f"VALUES (:t,'reboot_cpe',:c,repeat('a',64),now(),now() + interval '30 minutes','x',{vals})"), {"t": seed["A"], "c": cpe, "u": who["id"]})
    with pytest.raises(DBAPIError), migrated.begin() as c:   # an API record longer than 2 h
        c.execute(text("INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by, authorized_via, authorized_by_user_id) "
                       "VALUES (:t,'reboot_cpe',:c,repeat('a',64),now(),now() + interval '3 hours','x','api',:u)"), {"t": seed["A"], "c": cpe, "u": who["id"]})


def test_listing_shows_the_person_only_to_those_who_read_members(client, seed, migrated, lab):
    cpe = lab
    who = _member(migrated, seed, "noc_n2")
    h = _h(client, seed, who)
    _auth(client, h, cpe)
    mine = client.get(f"/v1/bench/authorizations?cpe_id={cpe}", headers=h).json()
    assert mine["can_authorize"] is True and mine["operations"] == ["reboot_cpe", "set_wifi_ssid"] and len(mine["items"]) == 1
    i = mine["items"][0]
    assert (i["via"], i["live"], i["mine"], i["by"], i["state"]) == ("api", True, True, None, "open")          # noc_n2 does not read members: no e-mail
    adm = client.get(f"/v1/bench/authorizations?cpe_id={cpe}", headers=hdr(client, "alice", seed, "A")).json()["items"][0]
    assert (adm["mine"], adm["by"]) == (False, who["email"])
    assert client.get("/v1/bench/authorizations", headers=hdr(client, "carol", seed, "A")).status_code == 403   # an auditor reads no jobs
    assert client.get("/v1/bench/authorizations", headers=hdr(client, "bob", seed, "B")).json()["items"] == []


def test_recent_second_factor_is_asked_when_enforced_and_no_connection_means_503(client, seed, migrated, lab, monkeypatch):
    cpe = lab
    h = _h(client, seed, _member(migrated, seed, "engineer"))
    monkeypatch.setenv("MFA_RECENT_ENFORCE", "true")
    settings.get_settings.cache_clear()
    try:
        r = _auth(client, h, cpe)
        assert (r.status_code, r.json()["detail"]) == (403, "mfa_recent_required")
    finally:
        monkeypatch.setenv("MFA_RECENT_ENFORCE", "false")
        settings.get_settings.cache_clear()
    from app.api import bench_authorizations as mod
    monkeypatch.setattr(mod, "get_rbac_engine", lambda: None)
    r = _auth(client, h, cpe)
    assert (r.status_code, r.json()["detail"]) == (503, "rbac_unavailable")
