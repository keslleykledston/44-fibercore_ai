"""RBAC delivery 5 (ADR-0031): platform delegation with a deadline, and MFA recency for the permissions that need it."""
from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import mfa, settings
from app.core.memberships import PLATFORM_ROLE
from app.core.security import hash_secret
from tests.conftest import JWT_SECRET

PW = "correct horse battery"


def _h(tok, tenant=None):
    return {"Authorization": f"Bearer {tok}", **({"X-Workspace-ID": str(tenant)} if tenant else {})}


@pytest.fixture(autouse=True)
def _forget_failed_attempts(migrated):
    """These tests fail second-factor codes on purpose, all from the one test client address: the per-source throttle must not leak into other modules."""
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM login_attempts"))


@pytest.fixture
def enforce(monkeypatch):
    def on(seconds: int | None = None):
        monkeypatch.setenv("MFA_RECENT_ENFORCE", "true")
        if seconds:
            monkeypatch.setenv("MFA_RECENT_SECONDS", str(seconds))
        settings.get_settings.cache_clear()
    yield on
    monkeypatch.delenv("MFA_RECENT_ENFORCE", raising=False)
    monkeypatch.delenv("MFA_RECENT_SECONDS", raising=False)
    settings.get_settings.cache_clear()


@pytest.fixture
def tenant(migrated):
    with migrated.begin() as c:
        return c.execute(text("INSERT INTO tenants(name) VALUES (:n) RETURNING id"), {"n": f"D{uuid4().hex[:6]}"}).scalar()


@pytest.fixture
def make(migrated):
    def create(role: str | None, tenant_id=None, *, operator=False):
        email = f"d{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash, is_platform_operator) VALUES (:e,:e,:h,:o) RETURNING id"),
                            {"e": email, "h": hash_secret(PW), "o": operator}).scalar()
            if role:
                c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": tenant_id, "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


def _login(client, who):
    r = client.post("/v1/auth/token", json={"email": who["email"], "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _with_mfa(client, who):
    """Enrol MFA; returns the recovery codes (each usable once as a second factor)."""
    j = _login(client, who)
    e = client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=_h(j["access_token"]))
    assert e.status_code == 200, e.text
    a = client.post("/v1/auth/mfa/activate", json={"code": mfa._hotp(e.json()["secret"], mfa.current_step())}, headers=_h(j["access_token"]))
    assert a.status_code == 200, a.text
    return list(a.json()["recovery_codes"])


def _session(client, who, code):
    j = _login(client, who)
    assert j["mfa_required"]
    r = client.post("/v1/auth/mfa/verify", json={"mfa_token": j["mfa_token"], "code": code})
    assert r.status_code == 200, r.text
    return r.json()


def _claims(tok):
    return jwt.decode(tok, JWT_SECRET, algorithms=["HS256"], audience="fibercore")


# ---------------------------------------------------------------- MFA recency
def test_login_with_a_second_factor_records_when_and_plain_login_does_not(client, make, tenant):
    plain = make("isp_admin", tenant)
    assert "mfa_at" not in _claims(_login(client, plain)["access_token"])
    strong = make("isp_admin", tenant)
    codes = _with_mfa(client, strong)
    before = time.time()
    s = _session(client, strong, codes[0])
    assert before - 2 <= _claims(s["access_token"])["mfa_at"] <= time.time() + 2


def test_refresh_carries_the_proof_and_never_renews_it(client, make, tenant, migrated):
    who = make("isp_admin", tenant)
    codes = _with_mfa(client, who)
    s = _session(client, who, codes[0])
    first = _claims(s["access_token"])["mfa_at"]
    with migrated.begin() as c:  # pretend the proof is old: a refresh must not make it young again
        c.execute(text("UPDATE refresh_tokens SET mfa_at = mfa_at - interval '30 minutes' WHERE user_id = :u"), {"u": who["id"]})
    r = client.post("/v1/auth/refresh", json={"refresh_token": s["refresh_token"]}).json()
    assert abs(_claims(r["access_token"])["mfa_at"] - (first - 1800)) < 5
    plain = _login(client, make("isp_admin", tenant))
    assert "mfa_at" not in _claims(client.post("/v1/auth/refresh", json={"refresh_token": plain["refresh_token"]}).json()["access_token"])


def test_with_enforcement_off_nothing_changes(client, make, tenant):
    who = make("isp_admin", tenant)
    other = make("noc_n1", tenant)
    tok = _login(client, who)["access_token"]  # no MFA at all
    r = client.put(f"/v1/members/{other['id']}/role", json={"role": "support", "reason": "teste de rotina"}, headers=_h(tok, tenant))
    assert r.status_code == 200, r.text


def test_enforced_permission_needs_a_recent_second_factor(client, make, tenant, enforce):
    enforce()
    admin, other = make("isp_admin", tenant), make("noc_n1", tenant)
    # no MFA at all: refused, and the answer says what to do
    tok = _login(client, admin)["access_token"]
    r = client.put(f"/v1/members/{other['id']}/role", json={"role": "support", "reason": "teste de rotina"}, headers=_h(tok, tenant))
    assert (r.status_code, r.json()["detail"]) == (403, "mfa_recent_required")
    # permissions that do not need it are untouched
    assert client.get("/v1/members", headers=_h(tok, tenant)).status_code == 200
    codes = _with_mfa(client, admin)
    s = _session(client, admin, codes[0])
    me = client.get("/v1/auth/me", headers=_h(s["access_token"], tenant)).json()
    assert me["mfa_recent"] == {"enforced": True, "window_seconds": 600, "satisfied": True}
    ok = client.put(f"/v1/members/{other['id']}/role", json={"role": "support", "reason": "teste de rotina"}, headers=_h(s["access_token"], tenant))
    assert ok.status_code == 200, ok.text


def test_the_window_closes_and_a_future_proof_does_not_count(client, make, tenant, enforce):
    enforce()
    admin, other = make("isp_admin", tenant), make("noc_n1", tenant)
    codes = _with_mfa(client, admin)
    _session(client, admin, codes[0])
    cfg = settings.get_settings()
    for at in (time.time() - 601, time.time() + 3600):
        tok = __import__("app.core.security", fromlist=["x"]).issue_token(cfg, sub=admin["id"], kind="user", mfa_at=at)
        r = client.put(f"/v1/members/{other['id']}/role", json={"role": "support", "reason": "teste de rotina"}, headers=_h(tok, tenant))
        assert (r.status_code, r.json()["detail"]) == (403, "mfa_recent_required"), at
    tok = __import__("app.core.security", fromlist=["x"]).issue_token(cfg, sub=admin["id"], kind="user", mfa_at=time.time() - 590)
    assert client.put(f"/v1/members/{other['id']}/role", json={"role": "support", "reason": "teste de rotina"}, headers=_h(tok, tenant)).status_code == 200


def test_step_up_gives_a_fresh_proof_and_is_bound_to_the_session(client, make, tenant, enforce, migrated):
    enforce()
    admin, other = make("isp_admin", tenant), make("noc_n1", tenant)
    codes = _with_mfa(client, admin)
    s = _session(client, admin, codes[0])
    with migrated.begin() as c:  # the proof from the login is now old
        c.execute(text("UPDATE refresh_tokens SET mfa_at = mfa_at - interval '1 hour' WHERE user_id = :u"), {"u": admin["id"]})
    old = client.post("/v1/auth/refresh", json={"refresh_token": s["refresh_token"]}).json()
    body = {"reason": "teste de rotina", "role": "support"}
    assert client.put(f"/v1/members/{other['id']}/role", json=body, headers=_h(old["access_token"], tenant)).status_code == 403
    # wrong code, another user's session, no session, and a bad bearer are all refused
    assert client.post("/v1/auth/mfa/step-up", json={"refresh_token": old["refresh_token"], "code": "000000"}, headers=_h(old["access_token"])).status_code == 401
    stranger = _login(client, make("isp_admin", tenant))
    assert client.post("/v1/auth/mfa/step-up", json={"refresh_token": stranger["refresh_token"], "code": codes[1]}, headers=_h(old["access_token"])).status_code == 401
    assert client.post("/v1/auth/mfa/step-up", json={"refresh_token": old["refresh_token"], "code": codes[1]}, headers={}).status_code == 401
    up = client.post("/v1/auth/mfa/step-up", json={"refresh_token": old["refresh_token"], "code": codes[1]}, headers=_h(old["access_token"]))
    assert up.status_code == 200, up.text
    assert up.json()["mfa_recent_seconds"] == 600
    assert client.put(f"/v1/members/{other['id']}/role", json=body, headers=_h(up.json()["access_token"], tenant)).status_code == 200
    # the proof lives on the session: the next refresh keeps it (inside the window)
    nxt = client.post("/v1/auth/refresh", json={"refresh_token": old["refresh_token"]}).json()
    assert time.time() - _claims(nxt["access_token"])["mfa_at"] < 60
    # the code is single-use
    assert client.post("/v1/auth/mfa/step-up", json={"refresh_token": nxt["refresh_token"], "code": codes[1]}, headers=_h(nxt["access_token"])).status_code == 401
    # a logged-out session cannot step up
    client.post("/v1/auth/logout", json={"refresh_token": nxt["refresh_token"]})
    assert client.post("/v1/auth/mfa/step-up", json={"refresh_token": nxt["refresh_token"], "code": codes[2]}, headers=_h(nxt["access_token"])).status_code == 401


def test_step_up_without_mfa_enrolled_is_a_clear_conflict(client, make, tenant):
    who = make("isp_admin", tenant)
    j = _login(client, who)
    r = client.post("/v1/auth/mfa/step-up", json={"refresh_token": j["refresh_token"], "code": "123456"}, headers=_h(j["access_token"]))
    assert (r.status_code, r.json()["detail"]) == (409, "mfa_not_enrolled")


def test_step_up_is_throttled(client, make, tenant):
    who = make("isp_admin", tenant)
    codes = _with_mfa(client, who)
    s = _session(client, who, codes[0])
    st = [client.post("/v1/auth/mfa/step-up", json={"refresh_token": s["refresh_token"], "code": "000000"}, headers=_h(s["access_token"])).status_code for _ in range(6)]
    assert st[:5] == [401] * 5 and st[5] == 429


# ---------------------------------------------------------------- delegation
def _operator(client, make):
    op = make(None, operator=True)
    return op, _with_mfa(client, op)


def _grant(client, admin_tok, tenant, email, **kw):
    return client.post("/v1/platform-delegations", json={"email": email, "reason": "chamado 123: diagnóstico da OLT", **kw}, headers=_h(admin_tok, tenant))


def test_a_platform_membership_can_no_longer_exist(migrated, tenant, make):
    who = make(None)
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,'platform_support')"), {"t": tenant, "u": who["id"]})


def test_delegation_gives_tenant_read_only_while_it_lives(client, make, tenant, migrated):
    admin = make("isp_admin", tenant)
    op, codes = _operator(client, make)
    atok = _login(client, admin)["access_token"]
    # before: the operator cannot even select the workspace
    s = _session(client, op, codes[0])
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 404
    assert client.get("/v1/auth/workspaces", headers=_h(s["access_token"])).json() == []
    g = _grant(client, atok, tenant, op["email"], hours=2)
    assert g.status_code == 201, g.text
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 200
    ws = client.get("/v1/auth/workspaces", headers=_h(s["access_token"])).json()
    assert [(w["tenant_id"], w["role"]) for w in ws] == [(str(tenant), PLATFORM_ROLE)]
    # nothing but tenant:read: no personal data, no members, no inventory, no audit
    for path in ("/v1/customers", "/v1/members", "/v1/inventory/olts", "/v1/platform-delegations", "/v1/audit"):
        assert client.get(path, headers=_h(s["access_token"], tenant)).status_code in (403, 404), path
    assert client.post("/v1/platform-delegations", json={"email": admin["email"], "reason": "tentativa de escalada indevida"}, headers=_h(s["access_token"], tenant)).status_code == 403
    # the deadline is the database's: a delegation that ran out stops working at once, with the same token
    with migrated.begin() as c:
        c.execute(text("ALTER TABLE membership_delegations DISABLE TRIGGER membership_delegations_immutable"))
        c.execute(text("ALTER TABLE membership_delegations DISABLE TRIGGER USER"))
        c.execute(text("UPDATE membership_delegations SET created_at = now() - interval '3 hours', expires_at = now() - interval '1 second' WHERE user_id = :u"), {"u": op["id"]})
        c.execute(text("ALTER TABLE membership_delegations ENABLE TRIGGER USER"))
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 404
    assert client.get("/v1/auth/workspaces", headers=_h(s["access_token"])).json() == []


def test_the_delegate_needs_mfa_like_any_privileged_role(client, make, tenant):
    admin = make("isp_admin", tenant)
    op = make(None, operator=True)  # has NOT enrolled MFA
    tok = _login(client, op)["access_token"]
    assert _grant(client, _login(client, admin)["access_token"], tenant, op["email"]).status_code == 201
    r = client.get("/v1/tenant", headers=_h(tok, tenant))
    assert (r.status_code, r.json()["detail"]) == (403, "mfa_enrolment_required")


def test_revoke_ends_it_immediately_and_is_idempotent_in_effect(client, make, tenant):
    admin = make("isp_admin", tenant)
    op, codes = _operator(client, make)
    atok = _login(client, admin)["access_token"]
    s = _session(client, op, codes[0])
    d = _grant(client, atok, tenant, op["email"]).json()
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 200
    r = client.delete(f"/v1/platform-delegations/{d['id']}", headers=_h(atok, tenant))
    assert r.status_code == 200 and r.json()["revoked"] == 1
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 404
    assert client.delete(f"/v1/platform-delegations/{d['id']}", headers=_h(atok, tenant)).status_code == 409
    assert client.delete(f"/v1/platform-delegations/{uuid4()}", headers=_h(atok, tenant)).status_code == 404


def test_renewing_replaces_and_only_one_is_live(client, make, tenant, migrated):
    admin = make("isp_admin", tenant)
    op, _ = _operator(client, make)
    atok = _login(client, admin)["access_token"]
    first = _grant(client, atok, tenant, op["email"], hours=1).json()
    second = _grant(client, atok, tenant, op["email"], hours=8)
    assert second.status_code == 201 and second.json()["replaced"] == 1
    items = client.get("/v1/platform-delegations", headers=_h(atok, tenant)).json()["items"]
    assert [i["status"] for i in items] == ["active", "revoked"]
    assert items[1]["id"] == first["id"] and items[0]["reason"].startswith("chamado")
    with migrated.connect() as c:
        assert c.execute(text("SELECT count(*) FROM membership_delegations WHERE user_id = :u AND revoked_at IS NULL"), {"u": op["id"]}).scalar_one() == 1


def test_grant_rules(client, make, tenant, migrated):
    admin = make("isp_admin", tenant)
    op, _ = _operator(client, make)
    ordinary = make(None)  # a normal account: indistinguishable from a missing one
    member = make("support", tenant)
    atok = _login(client, admin)["access_token"]
    unknown = _grant(client, atok, tenant, f"nobody{uuid4().hex[:6]}@example.com")
    not_op = _grant(client, atok, tenant, ordinary["email"])
    assert (unknown.status_code, unknown.json()) == (not_op.status_code, not_op.json()) == (404, {"detail": "operator_not_found"})
    assert _grant(client, atok, tenant, op["email"], hours=9).status_code == 422
    assert _grant(client, atok, tenant, op["email"], hours=0).status_code == 422
    assert client.post("/v1/platform-delegations", json={"email": op["email"], "reason": "curto"}, headers=_h(atok, tenant)).status_code == 422
    # a real member needs no delegation (and a delegation must never shadow a membership)
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_platform_operator = true WHERE id = :u"), {"u": member["id"]})
    r = _grant(client, atok, tenant, member["email"])
    assert (r.status_code, r.json()["detail"]) == (409, "already_member")
    # nobody delegates to themselves
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_platform_operator = true WHERE id = :u"), {"u": admin["id"]})
    assert _grant(client, atok, tenant, admin["email"]).status_code == 422


def test_only_the_workspace_administrator_manages_delegations(client, make, tenant):
    op, _ = _operator(client, make)
    for role, can_list, can_grant in (("isp_admin", True, True), ("access_manager", True, False), ("engineer", False, False),
                                      ("noc_n1", False, False), ("support", False, False), ("auditor", False, False)):
        who = make(role, tenant)
        if role == "access_manager":  # always needs MFA
            tok = _session(client, who, _with_mfa(client, who)[0])["access_token"]
        else:
            tok = _login(client, who)["access_token"]
        assert (client.get("/v1/platform-delegations", headers=_h(tok, tenant)).status_code == 200) is can_list, role
        assert (_grant(client, tok, tenant, op["email"]).status_code == 201) is can_grant, role


def test_a_delegation_never_crosses_workspaces_and_other_admins_cannot_touch_it(client, make, tenant, migrated):
    with migrated.begin() as c:
        other = c.execute(text("INSERT INTO tenants(name) VALUES ('Outro') RETURNING id")).scalar()
    admin, foreign_admin = make("isp_admin", tenant), make("isp_admin", other)
    op, codes = _operator(client, make)
    atok, ftok = _login(client, admin)["access_token"], _login(client, foreign_admin)["access_token"]
    d = _grant(client, atok, tenant, op["email"]).json()
    s = _session(client, op, codes[0])
    assert client.get("/v1/tenant", headers=_h(s["access_token"], other)).status_code == 404
    assert client.delete(f"/v1/platform-delegations/{d['id']}", headers=_h(ftok, other)).status_code == 404  # RLS: not even visible
    assert client.get("/v1/platform-delegations", headers=_h(ftok, other)).json()["items"] == []
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 200


def test_unmarking_the_operator_or_deactivating_the_account_ends_the_access(client, make, tenant, migrated):
    admin = make("isp_admin", tenant)
    op, codes = _operator(client, make)
    atok = _login(client, admin)["access_token"]
    _grant(client, atok, tenant, op["email"])
    s = _session(client, op, codes[0])
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 200
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_platform_operator = false WHERE id = :u"), {"u": op["id"]})
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 404
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_platform_operator = true, is_active = false WHERE id = :u"), {"u": op["id"]})
    assert client.get("/v1/tenant", headers=_h(s["access_token"], tenant)).status_code == 401


def test_grant_and_revocation_are_audited_and_the_row_is_a_record(client, make, tenant, migrated):
    admin = make("isp_admin", tenant)
    op, _ = _operator(client, make)
    atok = _login(client, admin)["access_token"]
    d = _grant(client, atok, tenant, op["email"], hours=3).json()
    client.delete(f"/v1/platform-delegations/{d['id']}", headers=_h(atok, tenant))
    with migrated.connect() as c:
        rows = c.execute(text("SELECT action, actor_id, evidence_redacted FROM audit_log WHERE tenant_id = :t AND action LIKE 'platform.delegation_%' ORDER BY created_at"),
                         {"t": tenant}).all()
        assert [r.action for r in rows] == ["platform.delegation_grant", "platform.delegation_revoke"]
        assert all(r.actor_id == admin["id"] for r in rows)
        assert rows[0].evidence_redacted["reason"].startswith("chamado") and rows[0].evidence_redacted["hours"] == 3
        events = c.execute(text("SELECT event_type FROM events_outbox WHERE tenant_id = :t AND event_type LIKE 'platform.delegation_%' ORDER BY created_at"),
                           {"t": tenant}).scalars().all()
        assert events == ["platform.delegation_grant", "platform.delegation_revoke"]
    for sql in ("UPDATE membership_delegations SET reason = 'outro motivo qualquer' WHERE id = :i",       # a revoked one cannot change at all
                "UPDATE membership_delegations SET expires_at = expires_at + interval '1 hour' WHERE id = :i",
                "UPDATE membership_delegations SET revoked_at = NULL, revoked_by = NULL WHERE id = :i"):
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text(sql), {"i": d["id"]})
    d2 = _grant(client, atok, tenant, op["email"]).json()  # a live one: only the revocation may change
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("UPDATE membership_delegations SET expires_at = expires_at + interval '1 hour' WHERE id = :i"), {"i": d2["id"]})
    # the database itself caps a delegation at 8 hours and forbids a self-grant
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("INSERT INTO membership_delegations(tenant_id,user_id,granted_by,reason,expires_at) VALUES (:t,:u,:g,'motivo suficiente', now() + interval '9 hours')"),
                  {"t": tenant, "u": op["id"], "g": admin["id"]})
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("INSERT INTO membership_delegations(tenant_id,user_id,granted_by,reason,expires_at) VALUES (:t,:u,:u,'motivo suficiente', now() + interval '1 hour')"),
                  {"t": tenant, "u": op["id"]})


def test_delegation_grant_asks_for_a_recent_second_factor_when_enforced(client, make, tenant, enforce):
    enforce()
    admin = make("isp_admin", tenant)
    op, _ = _operator(client, make)
    tok = _login(client, admin)["access_token"]
    r = _grant(client, tok, tenant, op["email"])
    assert (r.status_code, r.json()["detail"]) == (403, "mfa_recent_required")
    codes = _with_mfa(client, admin)
    s = _session(client, admin, codes[0])
    assert _grant(client, s["access_token"], tenant, op["email"]).status_code == 201
    assert client.delete(f"/v1/platform-delegations/{uuid4()}", headers=_h(tok, tenant)).json()["detail"] == "mfa_recent_required"
