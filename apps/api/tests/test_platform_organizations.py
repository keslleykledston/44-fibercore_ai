"""Criação de organização pela tela (ADR-0046 D1): rota de plataforma, função SECURITY DEFINER estreita, convite do primeiro administrador, auditoria em par, métrica.

Os testes de chamada DIRETA usam a role da aplicação (`app_url`), a mesma que a API usa: é ela que o ADR declara capaz de escolher `p_actor` (R-3). Provam o que o banco
garante sozinho: ator inexistente/inativo/não operador/sem segundo fator recente falham e não deixam NENHUMA linha; a role não insere em `tenants` por SQL; a função é atômica."""
from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core import features
from app.core.db import make_engine
from app.core.security import hash_secret, issue_token
from app.core.settings import get_settings
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session


@pytest.fixture(autouse=True)
def _window(migrated):
    """The hourly cap counts ALL `created` rows of the last hour: age whatever earlier tests left, so each test starts at zero (rows stay; only their clock moves)."""
    with migrated.begin() as c:
        c.execute(text("UPDATE audit_log SET created_at = created_at - interval '3 hours' WHERE action = 'platform.organization.created' AND created_at > now() - interval '2 hours'"))
        c.execute(text("DELETE FROM login_attempts"))
    yield


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, active=True, role=None, tenant_id=None):
        email = f"p{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash, is_platform_operator, is_active) VALUES (:e,:n,:h,:o,:a) RETURNING id"),
                            {"e": email, "n": f"Pessoa {email[:6]}", "h": hash_secret(PW), "o": operator, "a": active}).scalar()
            if role:
                c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": tenant_id, "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


@pytest.fixture
def operator(client, make):
    who = make(operator=True)
    who["session"] = _with_mfa_session(client, who)
    who["token"] = who["session"]["access_token"]
    return who


def _counts(migrated):
    with migrated.connect() as c:
        return tuple(c.execute(text(q)).scalar() for q in (
            "SELECT count(*) FROM tenants", "SELECT count(*) FROM member_invites", "SELECT count(*) FROM audit_log WHERE action LIKE 'platform.organization.%'",
            "SELECT count(*) FROM events_outbox WHERE event_type = 'platform.organization.created'"))


def _call_fn(engine, actor, **over):
    args = {"n": "Direta " + uuid4().hex[:8], "e": f"d{uuid4().hex[:8]}@example.com", "d": "Ana", "r": uuid4()}
    args.update({{"name": "n", "email": "e", "admin_name": "d", "request_id": "r"}[k]: v for k, v in over.items()})
    with engine.begin() as c:
        return c.execute(text("SELECT public.platform_create_organization(:a, :n, :e, :d, :r)"), {"a": actor, **args}).scalar_one()


# ================================================================== the route
def test_a_non_operator_gets_403_and_nothing_is_created(client, make, migrated):
    tenant = None
    with migrated.begin() as c:
        tenant = c.execute(text("INSERT INTO tenants(name) VALUES (:n) RETURNING id"), {"n": f"Org {uuid4().hex[:6]}"}).scalar()
    admin = make(role="isp_admin", tenant_id=tenant)
    s = _with_mfa_session(client, admin)           # an isp_admin WITH a recent second factor still has no way in: the role is irrelevant
    before = _counts(migrated)
    r, _ = _post(client, s["access_token"])
    assert r.status_code == 403 and r.json() == {"detail": "forbidden"}
    assert client.get("/v1/platform/organizations", headers=_h(s["access_token"])).status_code == 403
    assert _counts(migrated) == before


def test_missing_or_bad_credentials_are_401_and_a_service_token_is_403(client, seed, inv):
    assert client.post("/v1/platform/organizations", json={"name": "Xx", "admin_email": "a@b.co"}).status_code == 401
    assert client.get("/v1/platform/organizations", headers=_h("not-a-token")).status_code == 401
    from tests.conftest import agent
    h = agent(client, inv, "a1")
    assert client.post("/v1/platform/organizations", json={"name": "Xx", "admin_email": "a@b.co"}, headers=h).status_code == 403
    assert client.get("/v1/platform/organizations", headers=h).status_code == 403


def test_an_operator_without_a_recent_second_factor_gets_403(client, make, operator, migrated):
    plain = make(operator=True)
    tok = _login(client, plain)["access_token"]    # no MFA at all
    before = _counts(migrated)
    r, _ = _post(client, tok)
    assert r.status_code == 403 and r.json() == {"detail": "mfa_recent_required"}
    assert client.get("/v1/platform/organizations", headers=_h(tok)).status_code == 403
    old = issue_token(get_settings(), sub=operator["id"], kind="user", mfa_at=time.time() - 3600)   # a proof from an hour ago
    r, _ = _post(client, old)
    assert r.status_code == 403 and r.json() == {"detail": "mfa_recent_required"}
    future = issue_token(get_settings(), sub=operator["id"], kind="user", mfa_at=time.time() + 3600)
    assert _post(client, future)[0].status_code == 403
    assert _counts(migrated) == before


def test_a_deactivated_operator_is_refused_even_with_a_live_token(client, operator, migrated):
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_active = false WHERE id = :u"), {"u": operator["id"]})
    try:
        r, _ = _post(client, operator["token"])
        assert r.status_code == 401        # the same check every route makes: an inactive account's token does not count
    finally:
        with migrated.begin() as c:
            c.execute(text("UPDATE users_global SET is_active = true WHERE id = :u"), {"u": operator["id"]})


def test_the_operator_creates_an_organization_and_gets_one_invite_link(client, operator, migrated, seed):
    r, body = _post(client, operator["token"])
    assert r.status_code == 201, r.text
    assert r.headers["cache-control"] == "no-store"
    out = r.json()
    assert set(out) == {"tenant_id", "name", "request_id", "invite"}
    assert out["name"] == body["name"]
    inv = out["invite"]
    assert set(inv) == {"id", "state", "role", "email", "expires_at", "token"}
    assert inv["state"] == "pending" and inv["role"] == "isp_admin" and inv["email"] == body["admin_email"].lower() and len(inv["token"]) == 43
    tid = UUID(out["tenant_id"])
    with migrated.connect() as c:
        t = c.execute(text("SELECT name, status, demo FROM tenants WHERE id = :t"), {"t": tid}).one()
        assert (t.name, t.status, t.demo) == (body["name"], "active", False)
        i = c.execute(text("SELECT purpose, role, email, display_name, created_by, platform_origin, accepted_at, revoked_at, expires_at - created_at AS span, token_hash "
                           "FROM member_invites WHERE tenant_id = :t"), {"t": tid}).one()
        assert (i.purpose, i.role, i.email, i.display_name, i.created_by, i.platform_origin) == ("invite", "isp_admin", body["admin_email"].lower(), "Ana Admin", operator["id"], True)
        assert i.accepted_at is None and i.revoked_at is None and i.span.total_seconds() == 72 * 3600
        import hashlib
        assert bytes(i.token_hash) == hashlib.sha256(inv["token"].encode()).digest()      # only the SHA-256 is stored, and it is the one the existing invite lookup computes
        # the operator is NOT a member of what they created
        assert c.execute(text("SELECT count(*) FROM tenant_memberships WHERE tenant_id = :t"), {"t": tid}).scalar() == 0
        # the audit pair, same request id, with who/where
        rows = {r.action: r for r in c.execute(text("SELECT action, actor_id, evidence_redacted AS ev FROM audit_log WHERE tenant_id = :t AND action LIKE 'platform.organization.%'"), {"t": tid})}
        assert set(rows) == {"platform.organization.created", "platform.organization.requested"}
        created, requested = rows["platform.organization.created"], rows["platform.organization.requested"]
        assert created.ev["request_id"] == requested.ev["request_id"] == out["request_id"]
        assert created.actor_id == requested.actor_id == operator["id"]
        assert created.ev["actor_claimed"] == str(operator["id"]) and created.ev["session_user"] == "fibercore_app" and "application_name" in created.ev
        assert created.ev["admin_email"].endswith("***@example.com") and body["admin_email"] not in str(created.ev) and body["admin_email"] not in str(requested.ev)
        assert c.execute(text("SELECT count(*) FROM events_outbox WHERE tenant_id = :t AND event_type = 'platform.organization.created'"), {"t": tid}).scalar() == 1


def test_a_new_organization_is_empty_and_has_no_flags_switched_on(client, operator, migrated):
    r, _ = _post(client, operator["token"])
    tid = UUID(r.json()["tenant_id"])
    with migrated.connect() as c:
        for table in ("edges", "olts", "pon_ports", "onus", "cpes", "customers", "service_accounts", "tenant_memberships", "tenant_features", "jobs", "pops", "olt_secret_deliveries",
                      "membership_delegations", "bench_targets"):
            assert c.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": tid}).scalar() == 0, table   # noqa: S608
        c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(tid)})
        flags = features.resolve(c, tid)
    assert all(v["source"] == "default" for v in flags.values()), "no per-tenant override exists for a new organization"
    risky = {"fleet_manager", "fleet_secrets", "fleet_provision", "bench_writes", "erp_hubsoft", "ont_config", "olt_query", "speed_diagnostics", "profile_studio", "onu_discovery"}
    assert not {f for f in risky if flags[f]["enabled"]}, "everything that touches equipment or secrets starts OFF"


def test_the_invite_link_makes_the_first_administrator_and_nobody_else(client, operator, migrated):
    r, body = _post(client, operator["token"])
    out = r.json()
    token, tid = out["invite"]["token"], out["tenant_id"]
    pv = client.get(f"/v1/invites/{token}")
    assert pv.status_code == 200 and pv.json()["state"] == "valid" and pv.json()["tenant_name"] == body["name"] and pv.json()["email"] == body["admin_email"].lower()
    ok = client.post(f"/v1/invites/{token}/accept", json={"name": "Ana Admin", "password": "uma senha bem longa 123"})
    assert ok.status_code == 200, ok.text
    with migrated.connect() as c:
        members = c.execute(text("SELECT m.role, u.email FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id WHERE m.tenant_id = :t"), {"t": tid}).all()
    assert [(m.role, m.email) for m in members] == [("isp_admin", body["admin_email"].lower())]    # exactly one: the invited person, never the operator
    tok = client.post("/v1/auth/token", json={"email": body["admin_email"], "password": "uma senha bem longa 123"}).json()
    me = client.get("/v1/auth/me", headers=_h(tok["access_token"]))
    assert me.status_code == 200 and me.json()["tenant_id"] == tid and me.json()["role"] == "isp_admin"
    again = client.post(f"/v1/invites/{token}/accept", json={"name": "Ana Admin", "password": "uma senha bem longa 123"})
    assert again.status_code == 409          # one use only


def test_an_invite_of_a_demoted_operator_stops_working(client, operator, migrated):
    r, _ = _post(client, operator["token"])
    token = r.json()["invite"]["token"]
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_platform_operator = false WHERE id = :u"), {"u": operator["id"]})
    try:
        assert client.post(f"/v1/invites/{token}/accept", json={"name": "Ana", "password": "uma senha bem longa 123"}).status_code == 404   # invite_invalid: fail closed
    finally:
        with migrated.begin() as c:
            c.execute(text("UPDATE users_global SET is_platform_operator = true WHERE id = :u"), {"u": operator["id"]})


def test_ordinary_invites_still_need_an_inviter_who_is_a_member(client, make, migrated):
    """The change to the accept function is only for `platform_origin`: an invite made by a non-member (forged row) does NOT become acceptable."""
    with migrated.begin() as c:
        tid = c.execute(text("INSERT INTO tenants(name) VALUES (:n) RETURNING id"), {"n": f"Org {uuid4().hex[:6]}"}).scalar()
    outsider = make(operator=True)
    import hashlib
    tok = "T" * 43
    with migrated.begin() as c:
        c.execute(text("INSERT INTO member_invites(tenant_id, purpose, email, role, token_hash, created_by, expires_at) VALUES (:t,'invite','x@example.com','isp_admin',:h,:c, now() + interval '1 hour')"),
                  {"t": tid, "h": hashlib.sha256(tok.encode()).digest(), "c": outsider["id"]})
    assert client.post(f"/v1/invites/{tok}/accept", json={"name": "X", "password": "uma senha bem longa 123"}).status_code == 404


def test_platform_origin_is_only_for_the_first_isp_admin_invite(migrated):
    with migrated.begin() as c:
        tid = c.execute(text("INSERT INTO tenants(name) VALUES (:n) RETURNING id"), {"n": f"Org {uuid4().hex[:6]}"}).scalar()
        uid = c.execute(text("INSERT INTO users_global(email, display_name) VALUES (:e,'x') RETURNING id"), {"e": f"o{uuid4().hex[:6]}@example.com"}).scalar()
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("INSERT INTO member_invites(tenant_id, purpose, email, role, token_hash, created_by, expires_at, platform_origin) "
                       "VALUES (:t,'invite','y@example.com','engineer',decode(repeat('ab',32),'hex'),:u, now() + interval '1 hour', true)"), {"t": tid, "u": uid})


def test_validation_errors(client, operator, migrated):
    before = _counts(migrated)
    for over, expect in (({"name": "A"}, 422), ({"name": "x" * 61}, 422), ({"name": "   "}, 422), ({"name": "Nome\x07ruim"}, 422), ({"name": "x" * 201}, 422),
                         ({"admin_email": "isso-nao-e-email"}, 422), ({"admin_email": "a@b"}, 422), ({"admin_name": "y" * 201}, 422), ({"admin_name": "n" * 101}, 422)):
        r, _ = _post(client, operator["token"], **over)
        assert r.status_code == expect, (over, r.text)
    r = client.post("/v1/platform/organizations", json={"name": "Valido Ltda"}, headers=_h(operator["token"]))
    assert r.status_code == 422
    assert "isso-nao-e-email" not in str(_post(client, operator["token"], admin_email="isso-nao-e-email")[0].json())     # a rejected value is never echoed back
    assert _counts(migrated) == before


def test_a_duplicate_name_is_a_409_whatever_the_case_or_blanks(client, operator, migrated):
    name = f"Duplicada {uuid4().hex[:6]}"
    assert _post(client, operator["token"], name=name)[0].status_code == 201
    before = _counts(migrated)
    for variant in (name, name.upper(), f"  {name.lower()}  ", name.replace(" ", "   ")):
        r, _ = _post(client, operator["token"], name=variant)
        assert r.status_code == 409 and r.json() == {"detail": "organization_name_taken"}, variant
    assert _counts(migrated) == before
    # also against an organization the owner made by the CLI (a plain INSERT)
    with migrated.begin() as c:
        c.execute(text("INSERT INTO tenants(name) VALUES (:n)"), {"n": "Criada Pelo Dono"})
    assert _post(client, operator["token"], name="criada pelo dono")[0].status_code == 409


def test_at_most_five_organizations_per_hour(client, operator, migrated):
    for _ in range(5):
        assert _post(client, operator["token"])[0].status_code == 201
    before = _counts(migrated)
    r, _ = _post(client, operator["token"])
    assert r.status_code == 429 and r.json() == {"detail": "organization_rate_limited"} and r.headers["retry-after"] == "3600"
    assert _counts(migrated) == before
    with migrated.begin() as c:   # an hour later the door opens again
        c.execute(text("UPDATE audit_log SET created_at = created_at - interval '2 hours' WHERE action = 'platform.organization.created' AND created_at > now() - interval '1 hour'"))
    assert _post(client, operator["token"])[0].status_code == 201


def test_the_list_has_counts_and_labels_only(client, operator, migrated, seed, inv):
    r, body = _post(client, operator["token"])
    tid = r.json()["tenant_id"]
    with migrated.begin() as c:   # the invite of the first admin, a CLI-made organization and some inventory in the seeded tenant A
        c.execute(text("INSERT INTO tenants(name) VALUES (:n)"), {"n": f"Pelo CLI {uuid4().hex[:6]}"})
    ls = client.get("/v1/platform/organizations", headers=_h(operator["token"]))
    assert ls.status_code == 200 and ls.headers["cache-control"] == "no-store"
    items = ls.json()["items"]
    mine = next(i for i in items if i["id"] == tid)
    assert set(mine) == {"id", "name", "status", "created_at", "edges", "olts", "onus", "created_by", "created_via", "invite_state", "api_trail"}
    assert (mine["name"], mine["status"], mine["edges"], mine["olts"], mine["onus"], mine["invite_state"], mine["created_via"], mine["api_trail"]) == (body["name"], "active", 0, 0, 0, "pending", "screen", True)
    assert mine["created_by"] == f"Pessoa {operator['email'][:6]}"
    cli = next(i for i in items if i["name"].startswith("Pelo CLI"))
    assert cli["created_via"] == "cli" and cli["api_trail"] is None and cli["created_by"] is None and cli["invite_state"] is None
    seeded = next(i for i in items if i["id"] == str(seed["A"]))
    assert seeded["edges"] >= 1                         # counts come from the real inventory of that organization
    blob = str(ls.json())
    assert "@" not in blob, "no e-mail address (member, invitee or subscriber) is ever listed"
    for tenant_key in ("A", "B"):
        assert all(k in {"id", "name", "status", "created_at", "edges", "olts", "onus", "created_by", "created_via", "invite_state", "api_trail"} for k in next(i for i in items if i["id"] == str(seed[tenant_key])))


def test_platform_status_tells_only_the_callers_own_standing(client, make, operator, inv):
    from tests.conftest import agent
    assert client.get("/v1/platform/status").status_code == 401
    assert client.get("/v1/platform/status", headers=_h("nope")).status_code == 401
    ok = client.get("/v1/platform/status", headers=_h(operator["token"]))
    assert ok.status_code == 200 and ok.json() == {"operator": True, "mfa_recent": True} and ok.headers["cache-control"] == "no-store"
    no_mfa = _login(client, make(operator=True))["access_token"]
    assert client.get("/v1/platform/status", headers=_h(no_mfa)).json() == {"operator": True, "mfa_recent": False}
    plain = _login(client, make(operator=False))["access_token"]
    assert client.get("/v1/platform/status", headers=_h(plain)).json() == {"operator": False, "mfa_recent": False}
    stale = issue_token(get_settings(), sub=operator["id"], kind="user", mfa_at=time.time() - 3600)
    assert client.get("/v1/platform/status", headers=_h(stale)).json() == {"operator": True, "mfa_recent": False}
    assert client.get("/v1/platform/status", headers=agent(client, inv, "a1")).json() == {"operator": False, "mfa_recent": False}


def test_the_operator_never_becomes_a_member_nor_reads_the_organization(client, operator, migrated):
    r, _ = _post(client, operator["token"])
    tid = r.json()["tenant_id"]
    assert client.get("/v1/auth/workspaces", headers=_h(operator["token"])).json() == []        # not a member of anything created
    for path in ("/v1/olts", "/v1/tenant", "/v1/audit"):
        assert client.get(path, headers={**_h(operator["token"]), "X-Workspace-ID": tid}).status_code in (400, 403, 404), path


# ================================================================== the function, called DIRECTLY by the application role
@pytest.fixture
def stale_mfa_operator(client, make, migrated):
    who = make(operator=True)
    _with_mfa_session(client, who)
    with migrated.begin() as c:
        c.execute(text("UPDATE refresh_tokens SET mfa_at = now() - interval '30 minutes' WHERE user_id = :u"), {"u": who["id"]})
    return who


def test_direct_call_with_an_actor_that_does_not_exist_inactive_or_not_operator_fails_and_leaves_nothing(client, make, operator, stale_mfa_operator, app_engine, migrated):
    inactive = make(operator=True, active=False)
    with migrated.begin() as c:   # even a live session of an inactive account counts for nothing
        c.execute(text("INSERT INTO refresh_tokens(family_id, user_id, token_hash, expires_at, family_expires_at, mfa_at) VALUES (gen_random_uuid(), :u, decode(repeat('01',32),'hex'), now() + interval '1 day', now() + interval '1 day', now())"), {"u": inactive["id"]})
    nonop = make(operator=False)
    nonop_s = _with_mfa_session(client, nonop)            # not an operator, WITH a fresh second factor
    no_mfa = make(operator=True)                          # operator, but no session at all
    with migrated.begin() as c:                           # operator whose only session was signed out
        revoked = make(operator=True)
    _with_mfa_session(client, revoked)
    with migrated.begin() as c:
        c.execute(text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :u"), {"u": revoked["id"]})
    before = _counts(migrated)
    cases = [(uuid4(), "platform_forbidden"), (None, "platform_forbidden"), (inactive["id"], "platform_forbidden"), (nonop["id"], "platform_forbidden"),
             (no_mfa["id"], "mfa_recent_required"), (stale_mfa_operator["id"], "mfa_recent_required"), (revoked["id"], "mfa_recent_required")]
    assert nonop_s["access_token"]
    for actor, expect in cases:
        with pytest.raises(DBAPIError) as ei:
            _call_fn(app_engine, actor)
        assert ei.value.orig.diag.message_primary == expect, (actor, ei.value.orig.diag.message_primary)
    assert _counts(migrated) == before, "a refused call leaves no row anywhere"


def test_direct_call_validates_its_parameters_and_leaves_nothing(app_engine, operator, migrated):
    before = _counts(migrated)
    bad = [dict(name="A"), dict(name="x" * 61), dict(name=None), dict(name="ab\x07cd"), dict(email="semarroba"), dict(email="a@b"), dict(email=None),
           dict(email=("a" * 250) + "@example.com"), dict(admin_name="z" * 101), dict(request_id=None)]
    for kw in bad:
        with pytest.raises(DBAPIError):
            _call_fn(app_engine, operator["id"], **kw)
    assert _counts(migrated) == before


def test_the_application_role_cannot_insert_into_tenants_by_sql(app_engine, migrated):
    for sql in ("INSERT INTO tenants(name) VALUES ('invasor')", "INSERT INTO tenants(id, name) VALUES (gen_random_uuid(), 'invasor')"):
        with pytest.raises(ProgrammingError) as ei, app_engine.begin() as c:
            c.execute(text(sql))
        assert ei.value.orig.sqlstate == "42501"
    with pytest.raises(ProgrammingError), app_engine.begin() as c:
        c.execute(text("UPDATE tenants SET name = 'x'"))
    with pytest.raises(ProgrammingError), app_engine.begin() as c:
        c.execute(text("DELETE FROM tenants"))
    with pytest.raises(ProgrammingError), app_engine.begin() as c:     # nor the invite table, the very table the function writes
        c.execute(text("INSERT INTO member_invites(tenant_id, purpose, email, role, token_hash, created_by, expires_at, platform_origin) "
                       "VALUES (gen_random_uuid(),'invite','a@b.co','isp_admin',decode(repeat('ab',32),'hex'),gen_random_uuid(), now() + interval '1 hour', true)"))
    with migrated.connect() as c:
        assert not c.execute(text("SELECT 1 FROM tenants WHERE name = 'invasor'")).first()


def test_the_function_is_owned_by_the_schema_owner_with_a_fixed_search_path_and_narrow_execute(migrated):
    with migrated.connect() as c:
        for fn in ("platform_create_organization(uuid, text, text, text, uuid)", "platform_list_organizations(uuid)", "platform_assert_actor(uuid)"):
            r = c.execute(text("SELECT p.prosecdef, pg_get_userbyid(p.proowner) AS owner, p.proconfig, (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = 'tenants') AS table_owner "
                               "FROM pg_proc p WHERE p.oid = CAST(:f AS regprocedure)"), {"f": f"public.{fn}"}).one()
            assert r.prosecdef and r.owner == r.table_owner and r.owner not in ("fibercore_app", "fibercore_rbac", "fibercore_worker"), fn
            assert r.proconfig == ["search_path=pg_catalog, public"], fn
            assert not c.execute(text("SELECT has_function_privilege('public', CAST(:f AS regprocedure), 'EXECUTE')"), {"f": f"public.{fn}"}).scalar(), fn
            for role in ("fibercore_rbac", "fibercore_worker"):
                assert not c.execute(text("SELECT has_function_privilege(:r, CAST(:f AS regprocedure), 'EXECUTE')"), {"r": role, "f": f"public.{fn}"}).scalar(), (fn, role)
            granted = c.execute(text("SELECT has_function_privilege('fibercore_app', CAST(:f AS regprocedure), 'EXECUTE')"), {"f": f"public.{fn}"}).scalar()
            assert granted == (not fn.startswith("platform_assert")), fn     # the helper is internal: nobody but the owner runs it
        # the application role owns nothing at all (ADR: "a role da aplicação não é dona de nada")
        assert c.execute(text("SELECT count(*) FROM pg_class c WHERE c.relowner = (SELECT oid FROM pg_roles WHERE rolname = 'fibercore_app')")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM pg_proc p WHERE p.proowner = (SELECT oid FROM pg_roles WHERE rolname = 'fibercore_app')")).scalar() == 0


def test_the_helper_is_not_callable_by_the_application_role(app_engine, operator):
    with pytest.raises(ProgrammingError), app_engine.begin() as c:
        c.execute(text("SELECT public.platform_assert_actor(:a)"), {"a": operator["id"]})


def test_a_temporary_table_with_a_table_name_cannot_hijack_the_function(app_engine, operator, migrated):
    """`pg_temp` is searched FIRST for relations unless named: the function qualifies every `public.` relation, so shadows created by the application role change nothing."""
    with app_engine.connect() as c:
        c.execute(text("CREATE TEMP TABLE tenants (id uuid, name text)"))
        c.execute(text("CREATE TEMP TABLE audit_log (tenant_id uuid, action text, created_at timestamptz DEFAULT now())"))
        c.execute(text("CREATE TEMP TABLE users_global (id uuid, is_active boolean, is_platform_operator boolean)"))
        c.execute(text("INSERT INTO users_global VALUES (:a, false, false)"), {"a": operator["id"]})      # the shadow says: this actor is NOT an operator
        c.execute(text("INSERT INTO audit_log SELECT gen_random_uuid(), 'platform.organization.created', now() FROM generate_series(1, 6)"))   # the shadow says: the hourly cap is spent
        name = "Sombra " + uuid4().hex[:6]
        c.execute(text("INSERT INTO tenants VALUES (gen_random_uuid(), :n)"), {"n": name})                   # the shadow says: the name is taken
        out = c.execute(text("SELECT public.platform_create_organization(:a, :n, :e, NULL, :r)"), {"a": operator["id"], "n": name, "e": f"s{uuid4().hex[:6]}@example.com", "r": uuid4()}).scalar_one()
        c.commit()
    with migrated.connect() as c:
        assert c.execute(text("SELECT name FROM public.tenants WHERE id = :t"), {"t": out["tenant_id"]}).scalar() == name
        assert c.execute(text("SELECT count(*) FROM public.audit_log WHERE tenant_id = :t AND action = 'platform.organization.created'"), {"t": out["tenant_id"]}).scalar() == 1


def test_creation_is_atomic_a_failure_inside_the_invite_undoes_the_tenant(app_engine, operator, migrated):
    with migrated.begin() as c:
        c.execute(text("CREATE FUNCTION zz_fail_invite() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'zz_boom'; END $$"))
        c.execute(text("CREATE TRIGGER zz_fail BEFORE INSERT ON member_invites FOR EACH ROW WHEN (NEW.platform_origin) EXECUTE FUNCTION zz_fail_invite()"))
    try:
        before = _counts(migrated)
        with pytest.raises(DBAPIError) as ei:
            _call_fn(app_engine, operator["id"], name="Nao Deve Existir")
        assert ei.value.orig.diag.message_primary == "zz_boom"
        assert _counts(migrated) == before
        with migrated.connect() as c:
            assert not c.execute(text("SELECT 1 FROM tenants WHERE name = 'Nao Deve Existir'")).first()
    finally:
        with migrated.begin() as c:
            c.execute(text("DROP TRIGGER zz_fail ON member_invites; DROP FUNCTION zz_fail_invite()"))
    _call_fn(app_engine, operator["id"], name="Agora Existe " + uuid4().hex[:4])     # and it works again once the fault is gone


def test_a_failure_after_the_audit_row_also_undoes_everything(app_engine, operator, migrated):
    with migrated.begin() as c:
        c.execute(text("CREATE FUNCTION zz_fail_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.event_type = 'platform.organization.created' THEN RAISE EXCEPTION 'zz_boom2'; END IF; RETURN NEW; END $$"))
        c.execute(text("CREATE TRIGGER zz_fail2 BEFORE INSERT ON events_outbox FOR EACH ROW EXECUTE FUNCTION zz_fail_outbox()"))
    try:
        before = _counts(migrated)
        with pytest.raises(DBAPIError):
            _call_fn(app_engine, operator["id"])
        assert _counts(migrated) == before        # tenant, invite, audit row: all gone together
    finally:
        with migrated.begin() as c:
            c.execute(text("DROP TRIGGER zz_fail2 ON events_outbox; DROP FUNCTION zz_fail_outbox()"))


def test_a_direct_call_by_the_application_role_works_for_a_real_operator_and_is_the_accepted_limit_R3(app_engine, operator, migrated):
    """ADR-0046 D1, R-3 (ACCEPTED, not a new finding): the database cannot prove the operator started the call. What it DOES guarantee, and this pins: only NEW rows, the cap, nothing existing is read or changed,
    and the call leaves `created` WITHOUT the API's `requested` (what the metric counts)."""
    with migrated.connect() as c:
        snap = lambda: c.execute(text("SELECT (SELECT count(*) FROM tenants), (SELECT count(*) FROM tenant_memberships), (SELECT count(*) FROM olts), (SELECT count(*) FROM audit_log WHERE action NOT LIKE 'platform.organization.%')")).one()  # noqa: E731
        existing = snap()
    out = _call_fn(app_engine, operator["id"])
    assert set(out) == {"tenant_id", "invite"} and set(out["invite"]) == {"id", "token", "expires_at", "role"}
    with migrated.connect() as c:
        after = c.execute(text("SELECT (SELECT count(*) FROM tenants), (SELECT count(*) FROM tenant_memberships), (SELECT count(*) FROM olts), (SELECT count(*) FROM audit_log WHERE action NOT LIKE 'platform.organization.%')")).one()
        assert after[0] == existing[0] + 1 and after[1:] == existing[1:]
        acts = [r.action for r in c.execute(text("SELECT action FROM audit_log WHERE tenant_id = :t"), {"t": out["tenant_id"]})]
        assert acts == ["platform.organization.created"]          # no `requested`: only the route writes it
    for _ in range(4):
        _call_fn(app_engine, operator["id"])
    with pytest.raises(DBAPIError) as ei:
        _call_fn(app_engine, operator["id"])                       # the sixth in the hour: the cap holds even for a direct caller
    assert ei.value.orig.diag.message_primary == "organization_rate_limited"


def test_the_metric_counts_only_creations_made_outside_the_route(client, operator, app_engine, worker_url, migrated):
    w = make_engine(worker_url)
    try:
        def n():
            with w.connect() as c:
                return c.execute(text("SELECT app_metrics_snapshot()")).scalar_one()["organizations_without_api_trail"]
        base = n()
        assert _post(client, operator["token"])[0].status_code == 201          # through the route: the pair exists
        assert n() == base
        _call_fn(app_engine, operator["id"])                                    # direct: `created` alone
        assert n() == base + 1
        with migrated.begin() as c:                                             # older than 30 days: out of the window
            c.execute(text("UPDATE audit_log SET created_at = now() - interval '40 days' WHERE action = 'platform.organization.created' AND tenant_id IN "
                           "(SELECT tenant_id FROM audit_log a WHERE action = 'platform.organization.created' AND NOT EXISTS (SELECT 1 FROM audit_log r WHERE r.tenant_id = a.tenant_id AND r.action = 'platform.organization.requested'))"))
        assert n() == 0
    finally:
        w.dispose()


def test_the_list_function_also_checks_its_actor(app_engine, make):
    with pytest.raises(DBAPIError) as ei, app_engine.begin() as c:
        c.execute(text("SELECT public.platform_list_organizations(:a)"), {"a": make(operator=False)["id"]})
    assert ei.value.orig.diag.message_primary == "platform_forbidden"
    with pytest.raises(DBAPIError), app_engine.begin() as c:
        c.execute(text("SELECT public.platform_list_organizations(:a)"), {"a": uuid4()})


def test_concurrent_creations_cannot_exceed_the_cap_or_duplicate_a_name(app_engine, operator, migrated):
    import threading
    results: list[str] = []
    name = "Corrida " + uuid4().hex[:6]

    def go():
        try:
            _call_fn(app_engine, operator["id"], name=name)
            results.append("ok")
        except DBAPIError as exc:
            results.append(exc.orig.diag.message_primary)
    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count("ok") == 1 and results.count("organization_name_taken") == 3, results
