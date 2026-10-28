import time
from uuid import uuid4

import jwt
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests.conftest import JWT_SECRET, login


def test_no_token_401(client):
    assert client.get("/v1/tenant").status_code == 401
    assert client.get("/v1/platform/modules").status_code == 401


def test_bad_password_and_unknown_user_same_401(client):
    a = client.post("/v1/auth/token", json={"email": "alice@example.com", "password": "wrong-password"})
    b = client.post("/v1/auth/token", json={"email": "nobody@example.com", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_tampered_alg_none_and_expired_rejected(client, seed):
    now = int(time.time())
    base = {"iss": "fibercore-api", "aud": "fibercore", "sub": str(seed["alice"]), "kind": "user", "iat": now}
    none_tok = jwt.encode({**base, "exp": now + 60}, key=None, algorithm="none")
    expired = jwt.encode({**base, "exp": now - 10}, JWT_SECRET, algorithm="HS256")
    wrong_aud = jwt.encode({**base, "aud": "other", "exp": now + 60}, JWT_SECRET, algorithm="HS256")
    for t in (none_tok, expired, wrong_aud):
        assert client.get("/v1/auth/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_tenant_a_cannot_read_tenant_b(client, seed):
    h = login(client, "alice")
    ok = client.get("/v1/tenant", headers={**h, "X-Workspace-ID": str(seed["A"])})
    assert ok.status_code == 200 and ok.json()["name"] == "Tenant A"
    # alice has no membership in B -> 404, indistinguishable from nonexistent tenant
    denied = client.get("/v1/tenant", headers={**h, "X-Workspace-ID": str(seed["B"])})
    ghost = client.get("/v1/tenant", headers={**h, "X-Workspace-ID": str(uuid4())})
    assert denied.status_code == ghost.status_code == 404 and denied.json() == ghost.json()


def test_multi_tenant_user_must_choose_and_roles_differ(client, seed):
    h = login(client, "carol")
    assert client.get("/v1/tenant", headers=h).status_code == 400
    assert client.get("/v1/audit", headers={**h, "X-Workspace-ID": str(seed["A"])}).status_code == 200  # auditor
    assert client.get("/v1/audit", headers={**h, "X-Workspace-ID": str(seed["B"])}).status_code == 403  # engineer


def test_rbac_noc_n1_cannot_read_audit(client, seed):
    assert client.get("/v1/audit", headers=login(client, "dave")).status_code == 403


def test_rls_db_level_isolation_with_app_role(seed, app_url):
    """RLS enforced by PostgreSQL itself, independent of application checks."""
    from app.core.db import make_engine, scoped_connection
    eng = make_engine(app_url)
    with scoped_connection(eng, tenant_id=seed["A"]) as c:
        assert {r.name for r in c.execute(text("SELECT name FROM tenants"))} == {"Tenant A"}
        c.execute(text("INSERT INTO audit_log(tenant_id,action,target_type,target_id) VALUES (:t,'x','t','1')"), {"t": seed["A"]})
    with scoped_connection(eng) as c:  # no tenant context -> nothing visible (fail closed)
        assert c.execute(text("SELECT count(*) FROM tenants")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM audit_log")).scalar() == 0
    with scoped_connection(eng, tenant_id=seed["B"]) as c:
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action='x'")).scalar() == 0
    try:
        with scoped_connection(eng, tenant_id=seed["B"]) as c:  # WITH CHECK blocks cross-tenant write
            c.execute(text("INSERT INTO audit_log(tenant_id,action,target_type,target_id) VALUES (:t,'evil','t','1')"), {"t": seed["A"]})
        raise AssertionError("cross-tenant insert allowed")
    except (DBAPIError, ProgrammingError):
        pass


def test_app_role_is_not_privileged_and_audit_append_only(seed, app_url):
    from app.core.db import make_engine, scoped_connection
    eng = make_engine(app_url)
    with scoped_connection(eng) as c:
        row = c.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert (row.rolsuper, row.rolbypassrls) == (False, False)
    for stmt in ("UPDATE audit_log SET action='tamper'", "DELETE FROM audit_log", "INSERT INTO tenants(name) VALUES ('x')"):
        try:
            with scoped_connection(eng, tenant_id=seed["A"]) as c:
                c.execute(text(stmt))
            raise AssertionError(f"allowed: {stmt}")
        except (DBAPIError, ProgrammingError):
            pass


def test_service_account_scoped_to_its_tenant(client, seed):
    r = client.post("/v1/auth/service-token", json={"client_id": str(seed["sa"]), "client_secret": seed["sa_secret"]})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get("/v1/auth/me", headers=h).json()
    assert me["kind"] == "service" and me["tenant_id"] == str(seed["A"]) and me["role"] == "engineer"
    # X-Workspace-ID of another tenant is ignored for service tokens
    assert client.get("/v1/tenant", headers={**h, "X-Workspace-ID": str(seed["B"])}).json()["name"] == "Tenant A"
    bad = client.post("/v1/auth/service-token", json={"client_id": str(seed["sa"]), "client_secret": "nope"})
    assert bad.status_code == 401


def test_access_is_audited(client, seed):
    h = {**login(client, "alice"), "X-Workspace-ID": str(seed["A"])}
    client.get("/v1/tenant", headers=h)
    actions = [a["action"] for a in client.get("/v1/audit", headers=h).json()]
    assert "tenant.read" in actions



def test_workspaces_lists_only_own_memberships(client, seed):
    carol = client.get("/v1/auth/workspaces", headers=login(client, "carol")).json()
    assert {w["name"] for w in carol} == {"Tenant A", "Tenant B"} and {w["role"] for w in carol} == {"auditor", "engineer"}
    alice = client.get("/v1/auth/workspaces", headers=login(client, "alice")).json()
    assert [w["name"] for w in alice] == ["Tenant A"]
    assert client.get("/v1/auth/workspaces").status_code == 401


def test_service_token_cannot_list_workspaces(client, seed):
    r = client.post("/v1/auth/service-token", json={"client_id": str(seed["sa"]), "client_secret": seed["sa_secret"]})
    assert client.get("/v1/auth/workspaces", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 403


def test_tenant_names_not_visible_without_membership(seed, app_url):
    from sqlalchemy import text as t

    from app.core.db import make_engine, scoped_connection
    eng = make_engine(app_url)
    with scoped_connection(eng, user_id=seed["dave"]) as c:  # dave belongs only to A
        assert {r.name for r in c.execute(t("SELECT name FROM tenants"))} == {"Tenant A"}
    with scoped_connection(eng) as c:
        assert c.execute(t("SELECT count(*) FROM tenants")).scalar() == 0
