"""MFA_REQUIRED_ROLES: roles that must have MFA before using any tenant-scoped route (fail closed, no self-downgrade)."""
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core import mfa, settings
from app.core.security import hash_secret

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
def member(migrated, seed):
    """A fresh account per test (the seed users are session-scoped and shared): create(role) -> {email, id}."""
    def create(role: str, tenant: str = "A"):
        email = f"p{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:e,:h) RETURNING id"),
                            {"e": email, "h": hash_secret(PW)}).scalar()
            c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"),
                      {"t": seed[tenant], "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


def _token(client, who):
    r = client.post("/v1/auth/token", json={"email": who["email"], "password": PW})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _enrol(client, tok):
    e = client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=_bearer(tok))
    assert e.status_code == 200, e.text
    secret = e.json()["secret"]
    a = client.post("/v1/auth/mfa/activate", json={"code": mfa._hotp(secret, mfa.current_step())}, headers=_bearer(tok))
    assert a.status_code == 200, a.text
    return secret, a.json()["recovery_codes"]


def test_policy_off_by_default_changes_nothing(client, seed, member):
    tok = _token(client, member("isp_admin"))
    assert client.get("/v1/incidents", headers={**_bearer(tok), "X-Workspace-ID": str(seed["A"])}).status_code == 200
    assert client.get("/v1/auth/mfa/status", headers=_bearer(tok)).json()["required"] is False


def test_required_role_is_blocked_until_mfa_is_enabled_then_released(client, seed, member, policy):
    policy("isp_admin")
    tok = _token(client, member("isp_admin"))
    h = {**_bearer(tok), "X-Workspace-ID": str(seed["A"])}
    for path in ("/v1/incidents", "/v1/onus", "/v1/platform/modules"):
        r = client.get(path, headers=h)
        assert r.status_code == 403 and r.json()["detail"] == "mfa_enrolment_required", (path, r.status_code, r.text)
    st = client.get("/v1/auth/mfa/status", headers=_bearer(tok)).json()   # the MFA routes stay open so the user can comply
    assert st["required"] is True and st["enabled"] is False
    _enrol(client, tok)
    assert client.get("/v1/incidents", headers=h).status_code == 200
    assert client.get("/v1/auth/mfa/status", headers=_bearer(tok)).json() == {
        "enabled": True, "recovery_codes_left": 8, "enrolment_available": True, "required": True}


def test_other_roles_are_untouched(client, seed, member, policy):
    policy("isp_admin")
    tok = _token(client, member("noc_n1"))
    assert client.get("/v1/incidents", headers={**_bearer(tok), "X-Workspace-ID": str(seed["A"])}).status_code == 200
    assert client.get("/v1/auth/mfa/status", headers=_bearer(tok)).json()["required"] is False


def test_a_required_role_in_any_tenant_gates_every_tenant(client, seed, member, migrated, policy):
    policy("engineer")
    who = member("auditor", "A")
    with migrated.begin() as c:   # same person is an engineer in tenant B
        c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,'engineer')"), {"t": seed["B"], "u": who["id"]})
    tok = _token(client, who)
    r = client.get("/v1/incidents", headers={**_bearer(tok), "X-Workspace-ID": str(seed["A"])})
    assert r.status_code == 403 and r.json()["detail"] == "mfa_enrolment_required"


def test_a_required_user_cannot_switch_mfa_off(client, seed, member, policy):
    policy("isp_admin")
    tok = _token(client, member("isp_admin"))
    secret, recovery = _enrol(client, tok)
    r = client.post("/v1/auth/mfa/disable", json={"password": PW, "code": recovery[0]}, headers=_bearer(tok))
    assert r.status_code == 409
    assert client.get("/v1/auth/mfa/status", headers=_bearer(tok)).json()["enabled"] is True
    assert client.get("/v1/incidents", headers={**_bearer(tok), "X-Workspace-ID": str(seed["A"])}).status_code == 200


def test_a_non_required_user_can_still_disable(client, seed, member, policy):
    policy("isp_admin")
    tok = _token(client, member("noc_n1"))
    _, recovery = _enrol(client, tok)
    assert client.post("/v1/auth/mfa/disable", json={"password": PW, "code": recovery[0]}, headers=_bearer(tok)).status_code == 204


def test_policy_typos_fail_closed_at_startup_not_silently(policy):
    from app.core.settings import get_settings, required_mfa_roles
    policy("isp_admn")   # typo: would silently weaken the policy if ignored
    with pytest.raises(RuntimeError, match="unknown roles"):
        required_mfa_roles(get_settings())
    policy(" isp_admin , noc_n1 ")
    assert required_mfa_roles(get_settings()) == {"isp_admin", "noc_n1"}
    policy("")
    assert required_mfa_roles(get_settings()) == frozenset()


def test_the_api_refuses_to_boot_with_a_misspelt_role(policy):
    from fastapi.testclient import TestClient

    from app.main import app
    policy("isp_admn")
    with pytest.raises(RuntimeError, match="unknown roles"), TestClient(app):
        pass
    policy("isp_admin")
    with TestClient(app):   # a valid policy boots normally
        pass


def test_concurrent_activation_is_serialised_and_the_loser_gets_a_conflict(client, seed, member, migrated):
    """Two activations must not both succeed: the loser would hand out recovery codes the winner already replaced.
    Deterministic: a second connection holds the user_mfa row lock while the request runs; the request has to WAIT for it."""
    import threading
    import time

    who = member("isp_admin")
    tok = _token(client, who)
    e = client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=_bearer(tok))
    secret = e.json()["secret"]
    result: dict = {}

    def activate():
        result["r"] = client.post("/v1/auth/mfa/activate", json={"code": mfa._hotp(secret, mfa.current_step())}, headers=_bearer(tok))

    with migrated.begin() as holder:
        holder.execute(text("SELECT 1 FROM user_mfa WHERE user_id = :u FOR UPDATE"), {"u": who["id"]})
        t = threading.Thread(target=activate)
        t.start()
        time.sleep(1.0)
        assert t.is_alive() and "r" not in result, "activation did not wait for the row lock (concurrent activations are not serialised)"
        holder.execute(text("UPDATE user_mfa SET enabled = true WHERE user_id = :u"), {"u": who["id"]})  # the "winner" commits
    t.join(10)
    assert result["r"].status_code == 409, result["r"].text
    assert "recovery_codes" not in result["r"].json()
