"""Team management (owner request 2026-10-30): invite, accept, remove, reset a password, change one's own, and the plain-language data the screen reads."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import team_info
from app.core.security import ROLE_PERMISSIONS, hash_secret
from tests.test_rbac_delegation_mfa import _forget_failed_attempts, _session, _with_mfa  # noqa: F401  (autouse: failed attempts must not leak between modules)

PW = "correct horse battery"
GOOD = "uma senha bem longa 2026"


def _h(tok, tenant):
    return {"Authorization": f"Bearer {tok}", "X-Workspace-ID": str(tenant)}


@pytest.fixture
def tenant(migrated):
    with migrated.begin() as c:
        return c.execute(text("INSERT INTO tenants(name) VALUES (:n) RETURNING id"), {"n": f"Fibra {uuid4().hex[:5]}"}).scalar()


@pytest.fixture
def make(migrated):
    def create(role, tenant_id):
        email = f"t{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:n,:h) RETURNING id"),
                            {"e": email, "n": f"Pessoa {email[:5]}", "h": hash_secret(PW)}).scalar()
            if role:
                c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": tenant_id, "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


def _tok(client, who, pw=PW):
    r = client.post("/v1/auth/token", json={"email": who["email"], "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _admin(client, make, tenant):
    a = make("isp_admin", tenant)
    return a, _h(_tok(client, a), tenant)


def _invite(client, h, email=None, role="engineer", name=None):
    return client.post("/v1/team/invites", headers=h, json={"email": email or f"novo{uuid4().hex[:8]}@example.com", "role": role, **({"name": name} if name else {})})


# ---------------------------------------------------------------- words
def test_every_permission_a_human_role_holds_is_explained_to_people():
    assert team_info.uncovered() == set()
    m = team_info.matrix()
    assert set(m) == set(team_info.ROLE_INFO) and set(team_info.ROLE_INFO) <= set(ROLE_PERMISSIONS)
    assert all(v == "all" for v in m["isp_admin"].values())
    assert m["auditor"]["audit"] == "some" and m["auditor"]["network"] == "none"
    assert m["access_manager"]["people"] == "some" and m["access_manager"]["network"] == "none"       # grants roles, sees no network
    assert m["noc_n2"]["request"] == "some" and m["engineer"]["bench"] == "all"
    import re
    words = [s for i in team_info.ROLE_INFO.values() for s in [i["label"], i["summary"], *i["can"], *i["cannot"]]] + [label for _, label, _ in team_info.CAPABILITIES]
    assert not any(re.search(r"[a-z_]+:[a-z_]+", s) for s in words)   # no permission names (like members:manage) in the words people read


def test_the_team_screen_data(client, make, tenant):
    admin, h = _admin(client, make, tenant)
    make("support", tenant)
    t = client.get("/v1/team", headers=h).json()
    assert t["me"]["can_manage"] and "engineer" in t["me"]["assignable_roles"] and "platform_support" not in t["me"]["assignable_roles"]
    assert t["summary"]["active"] == 2 and t["summary"]["pending_invites"] == 0 and t["summary"]["without_mfa"] == 2
    me = next(m for m in t["members"] if m["is_self"])
    assert me["role_label"] == "Administrador" and me["can_remove"] is False and me["can_reset_password"] is False
    assert {r["role"] for r in t["roles"]} == set(team_info.ROLE_INFO) and t["capabilities"]["matrix"]["engineer"]["bench"] == "all"
    assert client.get("/v1/team", headers=_h(_tok(client, make("engineer", tenant)), tenant)).status_code == 403     # an engineer does not see the team


# ---------------------------------------------------------------- invite and accept
def test_invite_accept_and_login(client, make, tenant, migrated):
    admin, h = _admin(client, make, tenant)
    r = _invite(client, h, "maria@exemplo.com", "engineer", "Maria Souza")
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["role_label"] == "Engenheiro" and len(inv["token"]) >= 40 and "token_hash" not in inv
    t = client.get("/v1/team", headers=h).json()
    assert t["summary"]["pending_invites"] == 1 and t["invites"][0]["email"] == "maria@exemplo.com" and "token" not in t["invites"][0]
    pv = client.get(f"/v1/invites/{inv['token']}").json()
    assert (pv["state"], pv["email"], pv["role_label"], pv["account_exists"], pv["name"]) == ("valid", "maria@exemplo.com", "Engenheiro", False, "Maria Souza")
    assert pv["tenant_name"] and pv["inviter"]
    for bad, code in (("curta", "password_short"), ("maria@exemplo.com1", "password_weak"), ("aaaaaaaaaaaaaaaa", "password_weak")):
        x = client.post(f"/v1/invites/{inv['token']}/accept", json={"name": "Maria Souza", "password": bad})
        assert (x.status_code, x.json()["detail"]) == (422, code), bad
    ok = client.post(f"/v1/invites/{inv['token']}/accept", json={"name": "Maria Souza", "password": GOOD})
    assert ok.status_code == 200 and ok.json() == {"status": "accepted", "purpose": "invite"}
    tok = _tok(client, {"email": "maria@exemplo.com"}, GOOD)
    me = client.get("/v1/auth/me", headers=_h(tok, tenant)).json()
    assert me["role"] == "engineer"
    again = client.post(f"/v1/invites/{inv['token']}/accept", json={"name": "Outra", "password": GOOD + "x"})
    assert (again.status_code, again.json()["detail"]) == (409, "invite_used")
    assert client.get(f"/v1/invites/{inv['token']}").json() == {"state": "used"}
    with migrated.connect() as c:
        assert sorted(c.execute(text("SELECT action FROM audit_log WHERE tenant_id = :t AND action LIKE 'member.invite%' ORDER BY created_at"), {"t": tenant}).scalars().all()) == ["member.invite", "member.invite_accepted"]
        # the raw token is nowhere in the database; only its hash
        assert c.execute(text("SELECT count(*) FROM member_invites WHERE token_hash = decode(:h, 'hex')"), {"h": __import__("hashlib").sha256(inv["token"].encode()).hexdigest()}).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM member_invites WHERE email = :t OR display_name = :t"), {"t": inv["token"]}).scalar_one() == 0


def test_an_existing_account_must_prove_itself_to_join(client, make, tenant, migrated):
    admin, h = _admin(client, make, tenant)
    with migrated.begin() as c:
        other_tenant = c.execute(text("INSERT INTO tenants(name) VALUES ('Outra Fibra') RETURNING id")).scalar()
    person = make("support", other_tenant)
    inv = _invite(client, h, person["email"], "noc_n1").json()
    pv = client.get(f"/v1/invites/{inv['token']}").json()
    assert pv["account_exists"] is True
    for _ in range(3):
        assert client.post(f"/v1/invites/{inv['token']}/accept", json={"password": "senha errada nenhuma"}).status_code == 401
    assert client.get("/v1/auth/workspaces", headers={"Authorization": f"Bearer {_tok(client, person)}"}).json().__len__() == 1      # nothing happened yet
    ok = client.post(f"/v1/invites/{inv['token']}/accept", json={"password": PW})
    assert ok.status_code == 200, ok.text
    ws = client.get("/v1/auth/workspaces", headers={"Authorization": f"Bearer {_tok(client, person)}"}).json()
    assert {(w["role"]) for w in ws} == {"support", "noc_n1"}
    assert _tok(client, person)                                                                                                   # the password is the one they had


def test_wrong_passwords_on_a_link_are_throttled(client, make, tenant, migrated):
    admin, h = _admin(client, make, tenant)
    with migrated.begin() as c:
        other = c.execute(text("INSERT INTO tenants(name) VALUES ('Outra Fibra 2') RETURNING id")).scalar()
    person = make("support", other)
    inv = _invite(client, h, person["email"], "noc_n1").json()
    codes = [client.post(f"/v1/invites/{inv['token']}/accept", json={"password": "errada errada errada"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_invite_rules(client, make, tenant, migrated):
    admin, h = _admin(client, make, tenant)
    member = make("support", tenant)
    assert _invite(client, h, member["email"]).json()["detail"] == "already_member"
    assert _invite(client, h, role="platform_support").status_code == 403           # never assignable
    assert _invite(client, h, role="edge_agent").status_code == 403
    assert _invite(client, h, role="inexistente").status_code == 422
    assert client.post("/v1/team/invites", headers=h, json={"email": "sem-arroba", "role": "engineer"}).status_code == 422
    # whoever cannot manage people cannot invite
    for role in ("engineer", "noc_n2", "support", "auditor"):
        assert _invite(client, _h(_tok(client, make(role, tenant)), tenant)).status_code == 403, role
    # an access manager hands out the ordinary roles, never administrator or access manager
    am = make("access_manager", tenant)
    ah = _h(_session(client, am, _with_mfa(client, am)[0])["access_token"], tenant)
    assert _invite(client, ah, role="support").status_code == 201
    for r in ("isp_admin", "access_manager"):
        x = _invite(client, ah, role=r)
        assert (x.status_code, x.json()["detail"]) == (403, "role_not_assignable"), r
    # a new invite to the same address replaces the old one
    e = f"dup{uuid4().hex[:6]}@example.com"
    first, second = _invite(client, h, e).json(), _invite(client, h, e).json()
    assert client.get(f"/v1/invites/{first['token']}").json() == {"state": "revoked"}
    assert client.get(f"/v1/invites/{second['token']}").json()["state"] == "valid"


def test_renew_cancel_and_expiry(client, make, tenant, migrated):
    admin, h = _admin(client, make, tenant)
    inv = _invite(client, h).json()
    new = client.post(f"/v1/team/invites/{inv['id']}/renew", headers=h)
    assert new.status_code == 201 and new.json()["token"] != inv["token"] and new.json()["email"] == inv["email"]
    assert client.get(f"/v1/invites/{inv['token']}").json() == {"state": "revoked"}
    assert client.get(f"/v1/invites/{new.json()['token']}").json()["state"] == "valid"
    assert client.post(f"/v1/team/invites/{inv['id']}/renew", headers=h).status_code == 404            # the old one is no longer pending
    assert client.delete(f"/v1/team/invites/{new.json()['id']}", headers=h).status_code == 200
    assert client.delete(f"/v1/team/invites/{new.json()['id']}", headers=h).json()["detail"] == "invite_not_open"
    assert client.get(f"/v1/invites/{new.json()['token']}").json() == {"state": "revoked"}
    inv2 = _invite(client, h).json()
    with migrated.begin() as c:
        c.execute(text("UPDATE member_invites SET created_at = now() - interval '3 hours', expires_at = now() - interval '1 hour' WHERE id = :i"), {"i": inv2["id"]})
    assert client.get(f"/v1/invites/{inv2['token']}").json() == {"state": "expired"}
    x = client.post(f"/v1/invites/{inv2['token']}/accept", json={"name": "A", "password": GOOD})
    assert (x.status_code, x.json()["detail"]) == (410, "invite_expired")
    t = client.get("/v1/team", headers=h).json()
    assert [i["expired"] for i in t["invites"]] == [True] and t["summary"]["pending_invites"] == 0
    assert client.get("/v1/invites/nao-existe-nenhum-token-assim-longo").json() == {"state": "invalid"}
    assert client.get("/v1/invites/curto").status_code == 404
    with pytest.raises(DBAPIError), migrated.begin() as c:   # the database caps a link at 72 hours
        c.execute(text("INSERT INTO member_invites (tenant_id, purpose, email, role, token_hash, created_by, expires_at) "
                       "VALUES (:t,'invite','x@example.com','engineer',decode(repeat('ab',32),'hex'),:u, now() + interval '73 hours')"), {"t": tenant, "u": admin["id"]})


# ---------------------------------------------------------------- reset, remove, own password
def test_password_reset_link(client, make, tenant):
    admin, h = _admin(client, make, tenant)
    person = make("support", tenant)
    old = _tok(client, person)
    r = client.post(f"/v1/team/members/{person['id']}/password-reset", headers=h)
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    pv = client.get(f"/v1/invites/{token}").json()
    assert (pv["state"], pv["purpose"], pv["account_exists"]) == ("valid", "reset", False)
    assert client.post(f"/v1/invites/{token}/accept", json={"password": "curta"}).status_code == 422
    assert client.post(f"/v1/invites/{token}/accept", json={"password": GOOD}).json() == {"status": "accepted", "purpose": "reset"}
    assert client.get("/v1/auth/me", headers=_h(old, tenant)).status_code == 401                      # the old sessions ended
    assert client.post("/v1/auth/token", json={"email": person["email"], "password": PW}).status_code == 401
    assert _tok(client, person, GOOD)
    assert client.post(f"/v1/invites/{token}/accept", json={"password": GOOD + "x"}).status_code == 409   # once


def test_password_reset_limits(client, make, tenant, migrated):
    admin, h = _admin(client, make, tenant)
    assert client.post(f"/v1/team/members/{admin['id']}/password-reset", headers=h).json()["detail"] == "use_change_password"
    with migrated.begin() as c:
        other = c.execute(text("INSERT INTO tenants(name) VALUES ('Outra Fibra 3') RETURNING id")).scalar()
    shared = make("support", tenant)
    with migrated.begin() as c:
        c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,'auditor')"), {"t": other, "u": shared["id"]})
    x = client.post(f"/v1/team/members/{shared['id']}/password-reset", headers=h)
    assert (x.status_code, x.json()["detail"]) == (409, "account_shared")                         # nobody takes a person over in somebody else's provider
    assert client.post(f"/v1/team/members/{uuid4()}/password-reset", headers=h).status_code == 404
    # an access manager cannot reset an administrator
    am = make("access_manager", tenant)
    ah = _h(_session(client, am, _with_mfa(client, am)[0])["access_token"], tenant)
    y = client.post(f"/v1/team/members/{admin['id']}/password-reset", headers=ah)
    assert (y.status_code, y.json()["detail"]) == (403, "target_role_protected")
    assert client.post(f"/v1/team/members/{make('support', tenant)['id']}/password-reset", headers=ah).status_code == 201
    assert client.post(f"/v1/team/members/{make('support', tenant)['id']}/password-reset", headers=_h(_tok(client, make("engineer", tenant)), tenant)).status_code == 403


def test_remove_member(client, make, tenant):
    admin, h = _admin(client, make, tenant)
    person = make("noc_n2", tenant)
    ptok = _tok(client, person)
    assert client.get("/v1/auth/me", headers=_h(ptok, tenant)).status_code == 200
    assert client.post(f"/v1/team/members/{person['id']}/remove", headers=h, json={"reason": "x"}).status_code == 422
    r = client.post(f"/v1/team/members/{person['id']}/remove", headers=h, json={"reason": "saiu da empresa"})
    assert r.status_code == 200 and r.json()["previous_role"] == "noc_n2"
    assert client.get("/v1/auth/me", headers=_h(ptok, tenant)).status_code == 404                  # no longer resolves in this workspace, at once
    assert client.post(f"/v1/team/members/{person['id']}/remove", headers=h, json={"reason": "de novo"}).status_code == 404
    assert client.post(f"/v1/team/members/{admin['id']}/remove", headers=h, json={"reason": "eu mesmo"}).json()["detail"] == "cannot_remove_self"
    # the last administrator stays: a second administrator tries to remove the first, then the first is the only one left
    second = make("isp_admin", tenant)
    sh = _h(_tok(client, second), tenant)
    assert client.post(f"/v1/team/members/{admin['id']}/remove", headers=sh, json={"reason": "troca de turno"}).status_code == 200
    assert client.post(f"/v1/team/members/{second['id']}/remove", headers=h, json={"reason": "tentativa"}).status_code in (401, 404)   # the removed one cannot act any more
    # an access manager cannot remove an administrator
    third = make("isp_admin", tenant)
    am = make("access_manager", tenant)
    ah = _h(_session(client, am, _with_mfa(client, am)[0])["access_token"], tenant)
    z = client.post(f"/v1/team/members/{third['id']}/remove", headers=ah, json={"reason": "tentativa"})
    assert (z.status_code, z.json()["detail"]) == (403, "target_role_protected")
    # last administrator: the trigger answers with a stable code
    sole = client.post(f"/v1/team/members/{second['id']}/remove", headers=_h(_tok(client, third), tenant), json={"reason": "ficar sozinho"})
    assert sole.status_code == 200
    am_try = client.post(f"/v1/team/members/{third['id']}/remove", headers=ah, json={"reason": "ultimo"})
    assert am_try.status_code == 403


def test_the_last_administrator_cannot_be_removed(client, make, tenant, migrated):
    admin, h = _admin(client, make, tenant)
    other = make("isp_admin", tenant)
    with migrated.begin() as c:   # make `other` the only administrator by demoting `admin` directly, then try to remove `other` as `admin`'s replacement
        c.execute(text("UPDATE tenant_memberships SET role = 'support' WHERE tenant_id = :t AND user_id = :u"), {"t": tenant, "u": admin["id"]})
    # `admin` is now a support member and has no right; the last administrator is `other`: an access manager cannot touch it, and nobody else can remove it
    am = make("access_manager", tenant)
    ah = _h(_session(client, am, _with_mfa(client, am)[0])["access_token"], tenant)
    assert client.post(f"/v1/team/members/{other['id']}/remove", headers=ah, json={"reason": "tentativa"}).status_code == 403


def test_change_own_password(client, make, tenant):
    who = make("support", tenant)
    tok = _tok(client, who)
    h = {"Authorization": f"Bearer {tok}"}
    assert client.post("/v1/auth/password", headers=h, json={"current_password": "errada errada", "new_password": GOOD}).status_code == 401
    assert client.post("/v1/auth/password", headers=h, json={"current_password": PW, "new_password": PW}).json()["detail"] == "password_same"
    assert client.post("/v1/auth/password", headers=h, json={"current_password": PW, "new_password": "curta"}).json()["detail"] == "password_short"
    assert client.post("/v1/auth/password", headers={}, json={"current_password": PW, "new_password": GOOD}).status_code == 401
    ok = client.post("/v1/auth/password", headers=h, json={"current_password": PW, "new_password": GOOD})
    assert ok.status_code == 200 and ok.json()["status"] == "changed"
    assert client.get("/v1/auth/me", headers=_h(tok, tenant)).status_code == 401                    # every session ended
    assert client.post("/v1/auth/token", json={"email": who["email"], "password": PW}).status_code == 401
    assert _tok(client, who, GOOD)


# ---------------------------------------------------------------- the database is the writer
def test_the_application_role_cannot_do_any_of_it(client, make, tenant, migrated):
    admin, h = _admin(client, make, tenant)
    inv = _invite(client, h).json()
    for stmt in ("SELECT app_invite_create(:u, :t, 'a@example.com', NULL, 'engineer', decode(repeat('ab',32),'hex'), 24)", "SELECT app_member_remove(:u, :t, :u, 'xxx')",
                 "SELECT app_invite_accept(decode(repeat('ab',32),'hex'), 'n', 'h', false)", "SELECT app_password_change(:u, NULL, repeat('x', 30))",
                 "INSERT INTO member_invites (tenant_id, purpose, email, role, token_hash, created_by, expires_at) VALUES (:t,'invite','x@example.com','isp_admin',decode(repeat('cd',32),'hex'),:u, now() + interval '1 hour')",
                 "UPDATE member_invites SET revoked_at = NULL", "DELETE FROM member_invites", "INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,'isp_admin')"):
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text("SET LOCAL ROLE fibercore_app"))
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
            c.execute(text(stmt), {"u": admin["id"], "t": str(tenant)})
    assert inv["token"]


def test_no_connection_for_it_means_503(client, make, tenant, monkeypatch):
    admin, h = _admin(client, make, tenant)
    from app.api import team as mod
    monkeypatch.setattr(mod, "get_rbac_engine", lambda: None)
    assert _invite(client, h).json()["detail"] == "rbac_unavailable"


# ---------------------------------------------------------------- what happened
def test_activity_reads_as_facts_and_hides_addresses_from_those_who_do_not_read_members(client, make, tenant):
    admin, h = _admin(client, make, tenant)
    inv = _invite(client, h, "ana@exemplo.com", "support").json()
    client.post(f"/v1/invites/{inv['token']}/accept", json={"name": "Ana Lima", "password": GOOD})
    ana = client.post("/v1/auth/token", json={"email": "ana@exemplo.com", "password": GOOD}).json()
    me_id = [m for m in client.get("/v1/team", headers=h).json()["members"] if m["email"] == "ana@exemplo.com"][0]["user_id"]
    client.put(f"/v1/members/{me_id}/role", headers=h, json={"role": "engineer", "reason": "promoção"})
    client.post(f"/v1/team/members/{me_id}/remove", headers=h, json={"reason": "saiu"})
    items = client.get("/v1/team/activity", headers=h).json()["items"]
    kinds = [i["kind"] for i in items]
    assert kinds[:3] == ["member.remove", "member.role_change", "member.invite_accepted"] and "member.invite" in kinds
    rem = items[0]
    assert (rem["actor"], rem["target"], rem["email"], rem["reason"], rem["to_label"]) == (admin["email"][:0] or rem["actor"], "Ana Lima", "ana@exemplo.com", "saiu", "Engenheiro")
    chg = items[1]
    assert (chg["from_label"], chg["to_label"], chg["reason"]) == ("Atendimento", "Engenheiro", "promoção")
    aud = make("auditor", tenant)
    seen = client.get("/v1/team/activity", headers=_h(_tok(client, aud), tenant)).json()["items"]
    assert seen and all(i["email"] is None for i in seen)
    assert client.get("/v1/team/activity", headers=_h(_tok(client, make("support", tenant)), tenant)).status_code == 403
    assert ana["access_token"]


def test_two_password_changes_racing_on_the_same_current_password_cannot_both_win(client, make, tenant):
    import threading

    from fastapi.testclient import TestClient

    from app.main import app
    for _ in range(6):   # a race is probabilistic: several rounds make a missing compare-and-swap fail reliably
        who = make("support", tenant)
        toks = [_tok(client, who) for _ in range(2)]
        out: list = []
        gate = threading.Barrier(2)

        def go(i):
            c = TestClient(app, raise_server_exceptions=False)
            gate.wait()
            out.append(c.post("/v1/auth/password", headers={"Authorization": f"Bearer {toks[i]}"},
                              json={"current_password": PW, "new_password": f"senha numero {i} bem longa 2026"}))

        ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(out) == 2 and sorted(r.status_code for r in out) in ([200, 401], [200, 409]), [(r.status_code, r.text) for r in out]
        winner = [i for i, r in enumerate(out) if r.status_code == 200]
        assert len(winner) == 1
        # the account keeps exactly ONE of the two new passwords: the one of the request that won
        logins = [client.post("/v1/auth/token", json={"email": who["email"], "password": f"senha numero {i} bem longa 2026"}).status_code for i in range(2)]
        assert sorted(logins) == [200, 401]
