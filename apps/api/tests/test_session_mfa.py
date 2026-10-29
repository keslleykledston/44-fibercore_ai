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


def test_refresh_rotates_and_old_token_is_reuse(client, user, migrated):
    j = _login(client, user).json()
    r1 = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]})
    assert r1.status_code == 200 and r1.json()["refresh_token"] != j["refresh_token"]
    assert client.get("/v1/auth/workspaces", headers=_bearer(r1.json()["access_token"])).status_code == 200
    # replaying the consumed token after the grace window revokes the whole family, including the legitimately rotated token
    _age_used(migrated, j["refresh_token"])
    assert client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]}).status_code == 401
    assert client.post("/v1/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code == 401


def _age_used(migrated, refresh_token, seconds=60):
    from app.core.sessions import hash_refresh
    with migrated.begin() as c:
        c.execute(text("UPDATE refresh_tokens SET used_at = now() - make_interval(secs => :s) WHERE token_hash = :h"),
                  {"s": seconds, "h": hash_refresh(refresh_token)})


def test_concurrent_refresh_inside_grace_gets_sibling_not_revocation(client, user):
    j = _login(client, user).json()
    a = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]})
    b = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]})  # second tab, same cookie
    assert a.status_code == b.status_code == 200 and a.json()["refresh_token"] != b.json()["refresh_token"]
    # both successors stay usable; the family is intact
    assert client.post("/v1/auth/refresh", json={"refresh_token": a.json()["refresh_token"]}).status_code == 200
    assert client.post("/v1/auth/refresh", json={"refresh_token": b.json()["refresh_token"]}).status_code == 200


def test_second_replay_inside_grace_is_theft_and_revokes_family(client, user):
    j = _login(client, user).json()
    a = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]})
    b = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]})  # the one allowed sibling
    c = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]})  # a third presentation: not a tab race
    assert (a.status_code, b.status_code, c.status_code) == (200, 200, 401)
    for r in (a, b):  # every token of the family is dead, including the ones minted before the detection
        assert client.post("/v1/auth/refresh", json={"refresh_token": r.json()["refresh_token"]}).status_code == 401


def test_logout_revokes_successor_created_by_refresh(client, user):
    j = _login(client, user).json()
    r = client.post("/v1/auth/refresh", json={"refresh_token": j["refresh_token"]}).json()
    # logout with the already-consumed token still kills the successor (same family)
    assert client.post("/v1/auth/logout", json={"refresh_token": j["refresh_token"]}).status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": r["refresh_token"]}).status_code == 401


def _post(path, refresh_token):
    from fastapi.testclient import TestClient

    from app.main import app
    TestClient(app).post(path, json={"refresh_token": refresh_token})


def test_refresh_and_logout_race_leaves_no_live_session(user, migrated):
    import threading

    from fastapi.testclient import TestClient

    from app.main import app
    for _ in range(12):
        c = TestClient(app)
        j = _login(c, user).json()
        t1 = threading.Thread(target=_post, args=("/v1/auth/refresh", j["refresh_token"]))
        t2 = threading.Thread(target=_post, args=("/v1/auth/logout", j["refresh_token"]))
        t1.start(); t2.start(); t1.join(); t2.join()
        with migrated.connect() as cn:
            live = cn.execute(text("SELECT count(*) FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL AND expires_at > now()"),
                              {"u": user["id"]}).scalar_one()
        assert live == 0, "a refresh racing a logout must not leave a live token behind"


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
    assert st == {"enabled": True, "recovery_codes_left": 7, "enrolment_available": True, "required": False}


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
        monkeypatch.setenv("JWT_SECRET_PREVIOUS", JWT_SECRET)
        st.get_settings.cache_clear()
        legacy = jwt.encode({"iss": "fibercore-api", "aud": "fibercore", "sub": str(user["id"]), "kind": "user", "iat": int(time.time()),
                             "exp": int(time.time()) + 60}, JWT_SECRET, algorithm="HS256")  # pre-kid token signed with the old key
        assert client.get("/v1/auth/workspaces", headers=_bearer(legacy)).status_code == 200  # still valid during the window
        wrong = jwt.encode({"iss": "fibercore-api", "aud": "fibercore", "sub": str(user["id"]), "kind": "user", "iat": int(time.time()),
                            "exp": int(time.time()) + 60}, "some-other-secret-with-more-than-32-chars!!", algorithm="HS256")
        assert client.get("/v1/auth/workspaces", headers=_bearer(wrong)).status_code == 401
    finally:
        monkeypatch.undo(); st.get_settings.cache_clear()


def test_regenerate_recovery_codes_replaces_the_whole_set_and_is_proof_gated(client, user, migrated):
    secret, old, step = _enable_mfa(client, user)
    tok = _login(client, user).json()
    ch = client.post("/v1/auth/mfa/verify", json={"mfa_token": tok["mfa_token"], "code": old[0]})  # a session (consumes old[0])
    h = _bearer(ch.json()["access_token"])
    url = "/v1/auth/mfa/recovery-codes"
    assert client.post(url, json={"password": "wrong", "code": old[1]}, headers=h).status_code == 401
    assert client.post(url, json={"password": PW, "code": "000000"}, headers=h).status_code == 401
    assert client.get("/v1/auth/mfa/status", headers=h).json()["recovery_codes_left"] == 7  # failures changed nothing
    r = client.post(url, json={"password": PW, "code": old[1]}, headers=h)  # a current recovery code is accepted as the second factor
    assert r.status_code == 200, r.text
    new = r.json()["recovery_codes"]
    assert len(new) == 8 and not (set(new) & set(old))
    assert client.get("/v1/auth/mfa/status", headers=h).json()["recovery_codes_left"] == 8
    with migrated.begin() as c:  # EVERY old code is gone from the table (checked in the DB: eight wrong guesses would trip the throttle)
        hashes = [mfa.hash_recovery(x) for x in old]
        assert c.execute(text("SELECT count(*) FROM mfa_recovery_codes WHERE user_id=:u AND code_hash = ANY(:h)"), {"u": user["id"], "h": hashes}).scalar() == 0
    t = _login(client, user).json()
    assert client.post("/v1/auth/mfa/verify", json={"mfa_token": t["mfa_token"], "code": old[5]}).status_code == 401  # and one never-used old code fails
    t = _login(client, user).json()
    assert client.post("/v1/auth/mfa/verify", json={"mfa_token": t["mfa_token"], "code": new[0]}).status_code == 200  # a new one works
    with migrated.begin() as c:  # only hashes are stored: the clear code is not in the table
        assert c.execute(text("SELECT count(*) FROM mfa_recovery_codes WHERE user_id=:u AND code_hash = convert_to(:h,'UTF8')"),
                         {"u": user["id"], "h": new[1]}).scalar() == 0


def test_regenerate_needs_mfa_enabled_and_a_valid_session(client, user):
    h = _bearer(_login(client, user).json()["access_token"])
    assert client.post("/v1/auth/mfa/recovery-codes", json={"password": PW, "code": "123456"}, headers=h).status_code == 409
    assert client.post("/v1/auth/mfa/recovery-codes", json={"password": PW, "code": "123456"}).status_code == 401


def test_regenerate_is_throttled_like_a_login(client, user):
    _secret, old, _ = _enable_mfa(client, user)
    tok = _login(client, user).json()
    h = _bearer(client.post("/v1/auth/mfa/verify", json={"mfa_token": tok["mfa_token"], "code": old[0]}).json()["access_token"])
    codes = [client.post("/v1/auth/mfa/recovery-codes", json={"password": PW, "code": "000000"}, headers=h).status_code for _ in range(12)]
    assert codes[0] == 401 and 429 in codes
    assert client.post("/v1/auth/mfa/recovery-codes", json={"password": PW, "code": old[1]}, headers=h).status_code == 429
