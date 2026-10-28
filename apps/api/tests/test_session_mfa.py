import base64
import time
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import text

from app.core import mfa
from app.core.security import hash_secret
from tests.conftest import JWT_SECRET

PW = "correct horse battery"


@pytest.fixture
def user(migrated):
    """A fresh account per test so lockout counters and MFA state never leak between tests."""
    email = f"u{uuid4().hex[:10]}@example.com"
    with migrated.begin() as c:
        uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:e,:h) RETURNING id"),
                        {"e": email, "h": hash_secret(PW)}).scalar()
    return {"id": uid, "email": email}


def _login(client, user, password=PW):
    return client.post("/v1/auth/token", json={"email": user["email"], "password": password})


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def _enable_mfa(client, user):
    j = _login(client, user).json()
    e = client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=_bearer(j["access_token"]))
    assert e.status_code == 200, e.text
    secret = e.json()["secret"]
    step = mfa.current_step()
    a = client.post("/v1/auth/mfa/activate", json={"code": mfa._hotp(secret, step)}, headers=_bearer(j["access_token"]))
    assert a.status_code == 200, a.text
    return secret, a.json()["recovery_codes"], step


def test_totp_rfc6238_vector():
    # RFC 6238 Appendix B (SHA-1), secret "12345678901234567890", T=59s -> 94287082; we use 6 digits -> 287082
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert mfa._hotp(secret, 59 // 30) == "287082"


def test_login_returns_refresh_and_kid(client, user):
    j = _login(client, user).json()
    assert j["mfa_required"] is False and j["refresh_token"] and j["expires_in"] == 900
    assert jwt.get_unverified_header(j["access_token"])["kid"] == "k1"


def test_refresh_rotates_and_old_token_is_reuse(client, user):
    j = _login(client, user).json()
    r1 = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]})
    assert r1.status_code == 200 and r1.json()["refresh_token"] != j["refresh_token"]
    assert client.get("/v1/auth/workspaces", headers=_bearer(r1.json()["access_token"])).status_code == 200
    # replaying the consumed token revokes the whole family, including the legitimately rotated token
    assert client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]}).status_code == 401
    assert client.post("/v1/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code == 401


def test_refresh_unknown_expired_and_family_cap(client, user, migrated):
    assert client.post("/v1/auth/refresh", json={"refresh_token": "x" * 43}).status_code == 401
    j = _login(client, user).json()
    with migrated.begin() as c:
        c.execute(text("UPDATE refresh_tokens SET expires_at = now() - interval '1 second' WHERE user_id = :u"), {"u": user["id"]})
    assert client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]}).status_code == 401
    j = _login(client, user).json()
    with migrated.begin() as c:
        c.execute(text("UPDATE refresh_tokens SET family_expires_at = now() - interval '1 second' WHERE token_hash = :h"),
                  {"h": __import__("app.core.sessions", fromlist=["x"]).hash_refresh(j["refresh_token"])})
    assert client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]}).status_code == 401


def test_rotation_never_extends_family_expiry(client, user, migrated):
    j = _login(client, user).json()
    r = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]}).json()
    with migrated.connect() as c:
        rows = c.execute(text("SELECT family_expires_at, expires_at FROM refresh_tokens WHERE user_id = :u"), {"u": user["id"]}).all()
    assert len({r.family_expires_at for r in rows}) == 1 and all(r.expires_at <= r.family_expires_at for r in rows)
    assert r["refresh_token"]


def test_logout_revokes_family(client, user):
    j = _login(client, user).json()
    assert client.post("/v1/auth/logout", json={"refresh_token": j["refresh_token"]}).status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]}).status_code == 401
    assert client.post("/v1/auth/logout", json={"refresh_token": "y" * 43}).status_code == 204  # idempotent, silent


def test_refresh_denied_for_deactivated_user(client, user, migrated):
    j = _login(client, user).json()
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_active = false WHERE id = :u"), {"u": user["id"]})
    assert client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]}).status_code == 401


def test_refresh_token_stored_only_as_hash(client, user, migrated):
    j = _login(client, user).json()
    with migrated.connect() as c:
        blob = b"".join(bytes(r[0]) for r in c.execute(text("SELECT token_hash FROM refresh_tokens WHERE user_id = :u"), {"u": user["id"]}))
    assert j["refresh_token"].encode() not in blob


def test_mfa_enrol_login_flow_replay_and_recovery(client, user, migrated):
    secret, recovery, used_step = _enable_mfa(client, user)
    assert len(recovery) == 8
    with migrated.connect() as c:  # secret is encrypted at rest, never plaintext
        enc = bytes(c.execute(text("SELECT secret_enc FROM user_mfa WHERE user_id = :u"), {"u": user["id"]}).scalar())
    assert secret.encode() not in enc

    j = _login(client, user).json()
    assert j["mfa_required"] and j["access_token"] is None and j["refresh_token"] is None and j["mfa_token"]
    # the challenge is not an access token
    assert client.get("/v1/auth/workspaces", headers=_bearer(j["mfa_token"])).status_code == 401
    # a code from the step already consumed at activation is a replay
    assert client.post("/v1/auth/mfa/verify", json={"mfa_token": j["mfa_token"], "code": mfa._hotp(secret, used_step)}).status_code == 401
    # next step's code is valid (within the +-1 window) and works once
    code = mfa._hotp(secret, used_step + 1)
    ok = client.post("/v1/auth/mfa/verify", json={"mfa_token": j["mfa_token"], "code": code})
    assert ok.status_code == 200 and ok.json()["refresh_token"]
    assert client.get("/v1/auth/workspaces", headers=_bearer(ok.json()["access_token"])).status_code == 200
    assert client.post("/v1/auth/mfa/verify", json={"mfa_token": j["mfa_token"], "code": code}).status_code == 401
    # recovery code: single use
    j2 = _login(client, user).json()
    rc = client.post("/v1/auth/mfa/verify", json={"mfa_token": j2["mfa_token"], "code": recovery[0]})
    assert rc.status_code == 200
    assert client.post("/v1/auth/mfa/verify", json={"mfa_token": j2["mfa_token"], "code": recovery[0]}).status_code == 401
    st = client.get("/v1/auth/mfa/status", headers=_bearer(rc.json()["access_token"])).json()
    assert st == {"enabled": True, "recovery_codes_left": 7, "enrolment_available": True}


def test_mfa_verify_is_throttled(client, user):
    _enable_mfa(client, user)
    j = _login(client, user).json()
    codes = [client.post("/v1/auth/mfa/verify", json={"mfa_token": j["mfa_token"], "code": "000000"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_mfa_challenge_expired_or_wrong_audience_rejected(client, user):
    _enable_mfa(client, user)
    now = int(time.time())
    base = {"iss": "fibercore-api", "sub": str(user["id"]), "kind": "mfa", "iat": now}
    expired = jwt.encode({**base, "aud": "fibercore:mfa", "exp": now - 5}, JWT_SECRET, algorithm="HS256")
    access_like = jwt.encode({**base, "aud": "fibercore", "exp": now + 60}, JWT_SECRET, algorithm="HS256")
    for t in (expired, access_like):
        assert client.post("/v1/auth/mfa/verify", json={"mfa_token": t, "code": "123456"}).status_code == 401


def test_mfa_enrol_requires_password_and_disable_requires_factor(client, user):
    j = _login(client, user).json()
    h = _bearer(j["access_token"])
    assert client.post("/v1/auth/mfa/enroll", json={"password": "wrong-password"}, headers=h).status_code == 401
    secret, recovery, step = _enable_mfa(client, user)
    assert client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=h).status_code == 409
    assert client.post("/v1/auth/mfa/disable", json={"password": PW, "code": "000000"}, headers=h).status_code == 401
    assert client.post("/v1/auth/mfa/disable", json={"password": "wrong-password", "code": recovery[1]}, headers=h).status_code == 401
    assert client.post("/v1/auth/mfa/disable", json={"password": PW, "code": recovery[1]}, headers=h).status_code == 204
    assert _login(client, user).json()["mfa_required"] is False


def test_activation_needs_pending_enrolment(client, user):
    h = _bearer(_login(client, user).json()["access_token"])
    assert client.post("/v1/auth/mfa/activate", json={"code": "123456"}, headers=h).status_code == 401
    assert client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers={}).status_code == 401
    assert client.get("/v1/auth/mfa/status").status_code == 401


def test_key_rotation_kid(client, user, monkeypatch):
    from app.core import settings as st
    old_tok = _login(client, user).json()["access_token"]  # signed with k1 / JWT_SECRET
    new_secret = "new-secret-with-more-than-32-characters!!"
    monkeypatch.setenv("JWT_SECRET", new_secret); monkeypatch.setenv("JWT_KID", "k2")
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", JWT_SECRET); monkeypatch.setenv("JWT_KID_PREVIOUS", "k1")
    st.get_settings.cache_clear()
    try:
        assert client.get("/v1/auth/workspaces", headers=_bearer(old_tok)).status_code == 200  # previous key still verifies
        fresh = _login(client, user).json()["access_token"]
        assert jwt.get_unverified_header(fresh)["kid"] == "k2"
        assert client.get("/v1/auth/workspaces", headers=_bearer(fresh)).status_code == 200
        unknown = jwt.encode({"iss": "fibercore-api", "aud": "fibercore", "sub": str(user["id"]), "kind": "user", "iat": int(time.time()),
                              "exp": int(time.time()) + 60}, JWT_SECRET, algorithm="HS256", headers={"kid": "k9"})
        assert client.get("/v1/auth/workspaces", headers=_bearer(unknown)).status_code == 401  # unknown kid never falls back
        monkeypatch.setenv("JWT_SECRET_PREVIOUS", "")
        st.get_settings.cache_clear()
        assert client.get("/v1/auth/workspaces", headers=_bearer(old_tok)).status_code == 401  # previous key retired
    finally:
        monkeypatch.undo(); st.get_settings.cache_clear()
