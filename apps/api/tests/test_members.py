"""Members list + administrator MFA reset: re-authenticated, account-wide guard, audited, sessions revoked, throttled, fail closed."""
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core import mfa, settings
from app.core.security import hash_secret
from tests.conftest import hdr

PW = "correct horse battery"


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def policy(monkeypatch):
    def set_roles(roles: str):
        monkeypatch.setenv("MFA_REQUIRED_ROLES", roles)
        settings.get_settings.cache_clear()

    yield set_roles
    monkeypatch.delenv("MFA_REQUIRED_ROLES", raising=False)
    settings.get_settings.cache_clear()


@pytest.fixture
def make(migrated, seed):
    def create(role: str, tenant: str = "A"):
        email = f"m{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:e,:h) RETURNING id"),
                            {"e": email, "h": hash_secret(PW)}).scalar()
            c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": seed[tenant], "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


def _login(client, who):
    r = client.post("/v1/auth/token", json={"email": who["email"], "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _enrol(client, who):
    tok = _login(client, who)["access_token"]
    secret = client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=_bearer(tok)).json()["secret"]
    a = client.post("/v1/auth/mfa/activate", json={"code": mfa._hotp(secret, mfa.current_step())}, headers=_bearer(tok))
    assert a.status_code == 200, a.text
    return secret, a.json()["recovery_codes"]


def _admin_with_mfa(client, make, seed):
    adm = make("isp_admin")
    _secret, codes = _enrol(client, adm)
    tok = _login(client, adm)  # MFA is on now: the token endpoint answers with a challenge, finished at /v1/auth/mfa/verify
    assert tok["mfa_required"] is True
    r = client.post("/v1/auth/mfa/verify", json={"mfa_token": tok["mfa_token"], "code": codes.pop()})  # recovery codes: TOTP steps are single-use
    assert r.status_code == 200, r.text
    return adm, codes, {**_bearer(r.json()["access_token"]), "X-Workspace-ID": str(seed["A"])}


def _code(codes):
    return codes.pop()  # one single-use recovery code per sensitive action (the TOTP window only allows ~2 fresh codes per 30 s)


def test_list_members_is_tenant_scoped_and_needs_members_read(client, seed, make):
    ha = hdr(client, "alice", seed, "A")
    out = client.get("/v1/members", headers=ha).json()
    emails = {m["email"] for m in out["members"]}
    assert {"alice@example.com", "carol@example.com", "dave@example.com"} <= emails and "bob@example.com" not in emails
    assert out["can_reset_mfa"] is True and next(m for m in out["members"] if m["email"] == "alice@example.com")["is_self"] is True
    assert all("password" not in str(m) for m in out["members"])
    assert client.get("/v1/members", headers=hdr(client, "dave", seed, "A")).status_code == 403  # noc_n1


def test_reset_clears_mfa_recovery_codes_and_sessions_and_is_audited(client, seed, make, migrated):
    adm, codes, h = _admin_with_mfa(client, make, seed)
    target = make("engineer")
    target_secret, _ = _enrol(client, target)
    sess = client.post("/v1/auth/mfa/verify", json={"mfa_token": _login(client, target)["mfa_token"],
                                                     "code": "000000"})  # a bad code must not give a session
    assert sess.status_code == 401
    with migrated.begin() as c:  # an existing session of the target (refresh token) that the reset must kill
        fam = c.execute(text("SELECT gen_random_uuid()")).scalar()
        c.execute(text("INSERT INTO refresh_tokens(family_id, user_id, token_hash, expires_at, family_expires_at) "
                       "VALUES (:f,:u,decode(md5(random()::text),'hex'), now()+interval '1 day', now()+interval '1 day')"),
                  {"f": fam, "u": target["id"]})
    r = client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": PW, "code": _code(codes)}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "reset" and r.json()["revoked_sessions"] >= 1, r.text
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM user_mfa WHERE user_id=:u"), {"u": target["id"]}).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM mfa_recovery_codes WHERE user_id=:u"), {"u": target["id"]}).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM refresh_tokens WHERE user_id=:u AND revoked_at IS NULL"), {"u": target["id"]}).scalar() == 0
        ev = c.execute(text("SELECT actor_id, evidence_redacted::text AS ev FROM audit_log WHERE action='member.mfa_reset' AND target_id=:t"),
                       {"t": str(target["id"])}).one()
    assert ev.actor_id == adm["id"] and '"had_mfa": true' in ev.ev and target_secret not in ev.ev and PW not in ev.ev
    assert _login(client, target)["mfa_required"] is False  # the account is back to password-only until it re-enrols
    members = {m["email"]: m for m in client.get("/v1/members", headers=h).json()["members"]}
    assert members[target["email"]]["mfa_enabled"] is False


def test_guards_self_other_workspace_no_admin_mfa_wrong_credentials_and_roles(client, seed, make, migrated):
    adm, codes, h = _admin_with_mfa(client, make, seed)
    target = make("engineer")
    target_secret, _ = _enrol(client, target)
    body = {"password": PW, "code": _code(codes)}
    assert client.post(f"/v1/members/{adm['id']}/mfa/reset", json=body, headers=h).status_code == 409  # not yourself
    assert client.post(f"/v1/members/{seed['bob']}/mfa/reset", json=body, headers=h).status_code == 404  # another workspace's user
    assert client.post(f"/v1/members/{uuid4()}/mfa/reset", json=body, headers=h).status_code == 404
    carol = client.post(f"/v1/members/{seed['carol']}/mfa/reset", json=body, headers=h)  # carol is in A AND B: account-wide MFA
    assert carol.status_code == 409 and "other workspaces" in carol.text
    # a non-admin cannot, even with correct credentials
    eng = make("engineer")
    he = {**_bearer(_login(client, eng)["access_token"]), "X-Workspace-ID": str(seed["A"])}
    assert client.post(f"/v1/members/{target['id']}/mfa/reset", json=body, headers=he).status_code == 403
    # an administrator WITHOUT their own MFA cannot reset someone else's
    plain = make("isp_admin")
    hp = {**_bearer(_login(client, plain)["access_token"]), "X-Workspace-ID": str(seed["A"])}
    assert client.post(f"/v1/members/{target['id']}/mfa/reset", json=body, headers=hp).status_code == 409
    # wrong password / wrong code: 401, nothing changed
    assert client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": "nope", "code": _code(codes)}, headers=h).status_code == 401
    assert client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": PW, "code": "000000"}, headers=h).status_code == 401
    with migrated.begin() as c:
        assert c.execute(text("SELECT enabled FROM user_mfa WHERE user_id=:u"), {"u": target["id"]}).scalar() is True


def test_failed_reauthentication_attempts_are_recorded_and_lock_out(client, seed, make, migrated):
    adm, codes, h = _admin_with_mfa(client, make, seed)
    target = make("engineer")
    statuses = []
    for _ in range(12):
        r = client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": "wrong-password", "code": "123456"}, headers=h)
        statuses.append(r.status_code)
    assert statuses[0] == 401 and 429 in statuses, statuses  # the attempts persisted despite the failed request, so the throttle engaged
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM login_attempts WHERE key = :k AND NOT success"), {"k": f"reauth:{adm['id']}"}).scalar() >= 1
    ok = client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": PW, "code": _code(codes)}, headers=h)
    assert ok.status_code == 429  # even correct credentials are refused while locked


def test_reset_of_a_required_role_fails_closed_until_it_re_enrols(client, seed, make, policy):
    adm, codes, h = _admin_with_mfa(client, make, seed)
    target = make("engineer")
    target_secret, _ = _enrol(client, target)
    policy("engineer")
    r = client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": PW, "code": _code(codes)}, headers=h)
    assert r.status_code == 200
    ht = {**_bearer(_login(client, target)["access_token"]), "X-Workspace-ID": str(seed["A"])}
    blocked = client.get("/v1/incidents", headers=ht)
    assert blocked.status_code == 403 and blocked.json()["detail"] == "mfa_enrolment_required"  # reset never opens a hole


def test_membership_created_while_the_reset_waits_is_seen_and_refused(client, seed, make, migrated):
    """Deterministic TOCTOU check: another connection holds the per-account lock (as `app.cli add-member` does), the reset request waits
    on it, a second workspace membership appears and the lock is released: the reset must see it and answer 409, not delete the MFA."""
    import threading
    import time

    adm, codes, h = _admin_with_mfa(client, make, seed)
    target = make("engineer")
    _enrol(client, target)
    out: dict = {}

    def attempt():
        out["r"] = client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": PW, "code": _code(codes)}, headers=h)

    with migrated.begin() as holder:
        holder.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"account:{target['id']}"})
        t = threading.Thread(target=attempt)
        t.start()
        time.sleep(1.5)
        assert t.is_alive() and "r" not in out, "the reset did not wait for the account lock"
        holder.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,'support')"), {"t": seed["B"], "u": target["id"]})
    t.join(15)
    assert out["r"].status_code == 409 and "other workspaces" in out["r"].text, out["r"].text
    with migrated.begin() as c:
        assert c.execute(text("SELECT enabled FROM user_mfa WHERE user_id=:u"), {"u": target["id"]}).scalar() is True


def test_reset_kills_access_tokens_already_issued_not_only_refresh_tokens(client, seed, make):

    adm, codes, h = _admin_with_mfa(client, make, seed)
    target = make("engineer")
    _secret, tcodes = _enrol(client, target)
    ch = _login(client, target)
    s = client.post("/v1/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": tcodes.pop()})
    ht = {**_bearer(s.json()["access_token"]), "X-Workspace-ID": str(seed["A"])}
    assert client.get("/v1/incidents", headers=ht).status_code == 200  # the target's live session works...
    assert client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": PW, "code": _code(codes)}, headers=h).status_code == 200
    assert client.get("/v1/incidents", headers=ht).status_code == 401  # ...and dies at once, without waiting for expiry
    fresh = _login(client, target)  # a login right after the reset (same second) is a NEW session and works
    assert client.get("/v1/incidents", headers={**_bearer(fresh["access_token"]), "X-Workspace-ID": str(seed["A"])}).status_code == 200


def test_a_revoked_access_token_is_refused_by_every_user_route_not_just_tenant_ones(client, seed, make):
    adm, codes, h = _admin_with_mfa(client, make, seed)
    target = make("engineer")
    _secret, tcodes = _enrol(client, target)
    ch = _login(client, target)
    tok = client.post("/v1/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": tcodes.pop()}).json()["access_token"]
    bearer = _bearer(tok)
    assert client.get("/v1/auth/workspaces", headers=bearer).status_code == 200
    assert client.get("/v1/auth/mfa/status", headers=bearer).status_code == 200
    assert client.post(f"/v1/members/{target['id']}/mfa/reset", json={"password": PW, "code": _code(codes)}, headers=h).status_code == 200
    assert client.get("/v1/auth/workspaces", headers=bearer).status_code == 401
    assert client.get("/v1/auth/mfa/status", headers=bearer).status_code == 401
    assert client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=bearer).status_code == 401
    assert client.get("/v1/incidents", headers={**bearer, "X-Workspace-ID": str(seed["A"])}).status_code == 401


def test_a_deactivated_account_token_is_refused_by_the_mfa_routes_too(client, seed, make, migrated):
    who = make("engineer")
    tok = _login(client, who)["access_token"]
    assert client.get("/v1/auth/mfa/status", headers=_bearer(tok)).status_code == 200
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_active = false WHERE id = :u"), {"u": who["id"]})
    assert client.get("/v1/auth/mfa/status", headers=_bearer(tok)).status_code == 401


def test_refresh_that_races_a_reset_cannot_mint_a_session_after_it(client, seed, make, migrated):
    """Deterministic: a connection plays the reset (holds the per-account lock, then revokes + commits) while a refresh with the target's
    token is already in flight. The refresh must WAIT for the lock and then see the revocation (401), not mint a session from stale state."""
    import threading
    import time

    target = make("engineer")
    first = _login(client, target)  # no MFA: a plain session with a refresh token
    out: dict = {}

    def refresh():
        out["r"] = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})

    with migrated.begin() as holder:
        holder.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"account:{target['id']}"})
        t = threading.Thread(target=refresh)
        t.start()
        time.sleep(1.5)
        assert t.is_alive() and "r" not in out, "refresh did not wait for the account lock (it would read the token before the reset commits)"
        holder.execute(text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :u"), {"u": target["id"]})
        holder.execute(text("UPDATE users_global SET tokens_valid_after = clock_timestamp() WHERE id = :u"), {"u": target["id"]})
    t.join(15)
    assert out["r"].status_code == 401, out["r"].text


def test_cli_set_password_changes_the_login_and_ends_old_sessions(client, make, migrated, admin_url, monkeypatch, capsys):
    from app import cli

    who = make("engineer")
    old = _login(client, who)
    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    monkeypatch.setenv("NEW_PW_FOR_TEST", "a-brand-new-password-1!")
    cli.main(["set-password", who["email"], "--password-env", "NEW_PW_FOR_TEST"])
    out = capsys.readouterr().out
    assert "password updated" in out and "a-brand-new-password-1!" not in out  # the password is never printed
    assert client.post("/v1/auth/token", json={"email": who["email"], "password": PW}).status_code == 401  # old password dead
    assert client.post("/v1/auth/token", json={"email": who["email"], "password": "a-brand-new-password-1!"}).status_code == 200
    assert client.post("/v1/auth/refresh", json={"refresh_token": old["refresh_token"]}).status_code == 401  # old session ended
    assert client.get("/v1/auth/mfa/status", headers=_bearer(old["access_token"])).status_code == 401
    monkeypatch.setenv("NEW_PW_FOR_TEST", "short")
    with pytest.raises(SystemExit):
        cli.main(["set-password", who["email"], "--password-env", "NEW_PW_FOR_TEST"])  # same >= 12 rule as create-user


def test_regenerating_codes_waits_for_the_account_lock_and_then_sees_a_reset(client, seed, make, migrated):
    """Deterministic: a connection plays the administrator reset (holds the account lock, deletes the MFA, commits). The regeneration that
    started meanwhile must wait, then answer 409 (MFA gone) instead of minting codes for an account that no longer has MFA."""
    import threading
    import time

    who = make("engineer")
    _secret, codes = _enrol(client, who)
    s = client.post("/v1/auth/mfa/verify", json={"mfa_token": _login(client, who)["mfa_token"], "code": codes.pop()})
    h = _bearer(s.json()["access_token"])
    out: dict = {}

    def regen():
        out["r"] = client.post("/v1/auth/mfa/recovery-codes", json={"password": PW, "code": codes.pop()}, headers=h)

    with migrated.begin() as holder:
        holder.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"account:{who['id']}"})
        t = threading.Thread(target=regen)
        t.start()
        time.sleep(1.5)
        assert t.is_alive() and "r" not in out, "regeneration did not wait for the account lock"
        holder.execute(text("DELETE FROM user_mfa WHERE user_id = :u"), {"u": who["id"]})
        holder.execute(text("DELETE FROM mfa_recovery_codes WHERE user_id = :u"), {"u": who["id"]})
    t.join(15)
    assert out["r"].status_code == 409, out["r"].text
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM mfa_recovery_codes WHERE user_id = :u"), {"u": who["id"]}).scalar() == 0
