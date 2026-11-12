"""Helpers shared by the organization suites (creation, isolation): users, a session that PROVED the second factor just now, and the creation call."""
from __future__ import annotations

from uuid import uuid4

from app.core import mfa

PW = "correct horse battery"
GOOD_NAME = "Provedor Teste"


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _login(client, who):
    r = client.post("/v1/auth/token", json={"email": who["email"], "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _with_mfa_session(client, who):
    """Enrol MFA (the account then logs in in two steps) and return a session that proved the second factor just now."""
    j = _login(client, who)
    e = client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=_h(j["access_token"]))
    assert e.status_code == 200, e.text
    a = client.post("/v1/auth/mfa/activate", json={"code": mfa._hotp(e.json()["secret"], mfa.current_step())}, headers=_h(j["access_token"]))
    assert a.status_code == 200, a.text
    code = a.json()["recovery_codes"][0]
    j2 = _login(client, who)
    assert j2["mfa_required"]
    r = client.post("/v1/auth/mfa/verify", json={"mfa_token": j2["mfa_token"], "code": code})
    assert r.status_code == 200, r.text
    who["codes"] = a.json()["recovery_codes"][1:]
    return r.json()


def _post(client, token, **over):
    body = {"name": GOOD_NAME + " " + uuid4().hex[:6], "admin_email": f"adm{uuid4().hex[:8]}@example.com", "admin_name": "Ana Admin"}
    body.update(over)
    return client.post("/v1/platform/organizations", json=body, headers=_h(token)), body
