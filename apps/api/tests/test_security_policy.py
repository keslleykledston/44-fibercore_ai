"""Política de segurança por organização (ADR-0049 D1): MFA obrigatório por papel que só aperta o piso do ambiente; aplicada a cada requisição; isolada por organização."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core import security_policy
from app.core.db import make_engine
from app.core.security import hash_secret
from app.core.settings import get_settings
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, role=None, tenant_id=None):
        email = f"p{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash, is_platform_operator) VALUES (:e,:n,:h,:o) RETURNING id"),
                            {"e": email, "n": f"Pessoa {email[:6]}", "h": hash_secret(PW), "o": operator}).scalar()
            if role:
                c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": tenant_id, "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


@pytest.fixture
def operator(client, make):
    who = make(operator=True)
    who["token"] = _with_mfa_session(client, who)["access_token"]
    return who


@pytest.fixture(autouse=True)
def _window(migrated):
    with migrated.begin() as c:
        c.execute(text("UPDATE audit_log SET created_at = created_at - interval '3 hours' WHERE action = 'platform.organization.created' AND created_at > now() - interval '2 hours'"))
    yield


def _new_org(client, operator, make):
    r, _ = _post(client, operator["token"])
    assert r.status_code == 201, r.text
    tid = r.json()["tenant_id"]
    return {"id": tid, "admin": make(role="isp_admin", tenant_id=tid), "support": make(role="support", tenant_id=tid), "noc": make(role="noc_n1", tenant_id=tid)}


@pytest.fixture
def org(client, operator, make):
    return _new_org(client, operator, make)


def _tok(client, who):
    return _login(client, who)["access_token"]


def _put(client, who, roles):
    return client.put("/v1/security-policy", json={"mfa_required_roles": roles}, headers=_h(_tok(client, who)))


def test_the_default_is_only_the_environment_floor(client, org):
    v = client.get("/v1/security-policy", headers=_h(_tok(client, org["support"]))).json()
    assert v["organization"] == [] and set(v["floor"]) == {"access_manager", "platform_support"} and v["effective"] == v["floor"]
    assert v["can_edit"] is False and v["mfa_available"] is True and "isp_admin" in v["selectable"] and "edge_agent" not in v["selectable"]


def test_only_an_administrator_changes_it(client, org):
    assert _put(client, org["support"], ["noc_n1"]).status_code == 403
    assert _put(client, org["noc"], ["noc_n1"]).status_code == 403
    r = _put(client, org["admin"], ["noc_n1"])
    assert r.status_code == 200 and r.json()["changed"] is True and r.json()["organization"] == ["noc_n1"]


def test_tightening_is_enforced_on_every_request_for_that_role_only_and_enrolling_opens_it_again(client, org, make, operator):
    other = _new_org(client, operator, make)
    assert _put(client, org["admin"], ["noc_n1"]).status_code == 200
    h = _h(_tok(client, org["noc"]))
    r = client.get("/v1/security-policy", headers=h)
    assert r.status_code == 403 and r.json() == {"detail": "mfa_enrolment_required"}
    assert client.get("/v1/security-policy", headers=_h(_tok(client, org["support"]))).status_code == 200      # another role of the same organization: untouched
    assert client.get("/v1/security-policy", headers=_h(_tok(client, other["noc"]))).status_code == 200        # the same role in ANOTHER organization: untouched
    sess = _with_mfa_session(client, org["noc"])                                                                  # the person enrols (the /v1/auth routes stay open) ...
    assert client.get("/v1/security-policy", headers=_h(sess["access_token"])).status_code == 200                # ... and is in
    st = client.get("/v1/auth/mfa/status", headers=_h(sess["access_token"])).json()
    assert st["required"] is True


def test_it_never_goes_below_the_floor_and_clearing_it_releases_only_what_the_organization_added(client, org, make):
    assert _put(client, org["admin"], ["support"]).status_code == 200
    assert client.get("/v1/security-policy", headers=_h(_tok(client, org["support"]))).status_code == 403
    cleared = _put(client, org["admin"], [])
    assert cleared.status_code == 200 and cleared.json()["changed"] is True and cleared.json()["organization"] == []
    assert set(cleared.json()["effective"]) == {"access_manager", "platform_support"}                         # the floor stays
    assert client.get("/v1/security-policy", headers=_h(_tok(client, org["support"]))).status_code == 200
    manager = make(role="access_manager", tenant_id=org["id"])                                                    # the environment's floor still binds this role
    assert client.get("/v1/security-policy", headers=_h(_tok(client, manager))).status_code == 403


def test_an_administrator_cannot_lock_themselves_out_or_lock_everyone_out_without_an_authenticator(client, org, monkeypatch):
    r = _put(client, org["admin"], ["isp_admin"])
    assert r.status_code == 409 and r.json() == {"detail": "enable_your_mfa_first"}
    sess = _with_mfa_session(client, org["admin"])
    ok = client.put("/v1/security-policy", json={"mfa_required_roles": ["isp_admin"]}, headers=_h(sess["access_token"]))
    assert ok.status_code == 200 and ok.json()["organization"] == ["isp_admin"]
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    try:
        no_key = client.put("/v1/security-policy", json={"mfa_required_roles": ["support"]}, headers=_h(sess["access_token"]))
        assert no_key.status_code == 409 and no_key.json() == {"detail": "mfa_unavailable"}
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


@pytest.mark.parametrize("roles", [["edge_agent"], ["platform_support"], ["root"], ["support", "nobody"]])
def test_invalid_roles_are_refused(client, org, roles):
    assert _put(client, org["admin"], roles).status_code == 422


def test_idempotent_audited_and_evented(client, org, migrated):
    assert _put(client, org["admin"], ["support", "noc_n1", "support"]).json()["organization"] == ["noc_n1", "support"]
    again = _put(client, org["admin"], ["noc_n1", "support"])
    assert again.status_code == 200 and again.json()["changed"] is False
    with migrated.connect() as c:
        a = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE tenant_id = :t AND action = 'tenant.security_policy.changed'"), {"t": org["id"]}).all()
        ev = c.execute(text("SELECT count(*) FROM events_outbox WHERE tenant_id = :t AND event_type = 'tenant.security_policy.changed'"), {"t": org["id"]}).scalar()
    assert len(a) == 1 and a[0][0]["from"] == [] and a[0][0]["to"] == ["noc_n1", "support"] and ev == 1


def test_the_database_enforces_the_role_list_and_the_application_cannot_delete(org, app_engine):
    with pytest.raises(DBAPIError), app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
        c.execute(text("INSERT INTO tenant_security_policy (tenant_id, mfa_required_roles) VALUES (:t, ARRAY['edge_agent'])"), {"t": org["id"]})
    with pytest.raises(ProgrammingError), app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
        c.execute(text("DELETE FROM tenant_security_policy"))


def test_a_member_reads_only_the_policy_of_the_organizations_they_belong_to(client, org, operator, make, app_engine):
    other = _new_org(client, operator, make)
    assert _put(client, other["admin"], ["engineer"]).status_code == 200
    me = org["support"]
    with app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(me["id"])})
        rows = c.execute(text("SELECT tenant_id FROM tenant_security_policy")).all()
        assert all(str(r[0]) != str(other["id"]) for r in rows)
        assert security_policy.mfa_required(c, get_settings(), {other["id"]: "engineer"}) is False   # not a member there: no row visible, so only the floor applies
