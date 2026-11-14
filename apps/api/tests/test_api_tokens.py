"""Tokens de API por organização (ADR-0051 D1): integração de LEITURA que não é pessoa. Segredo mostrado uma vez, só o hash guardado; lista fechada de permissões de leitura; revogação e
validade; organização suspensa fecha o token; limite de taxa próprio; nada vaza para outra organização nem para a trilha."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.api import deps
from app.core import api_tokens
from app.core.db import make_engine
from app.core.security import hash_secret
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, role=None, tenant_id=None):
        email = f"t{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash, is_platform_operator) VALUES (:e,:n,:h,:o) RETURNING id"),
                            {"e": email, "n": f"Pessoa {email[:6]}", "h": hash_secret(PW), "o": operator}).scalar()
            if role:
                c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": tenant_id, "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


@pytest.fixture(autouse=True)
def _window(migrated):
    with migrated.begin() as c:
        c.execute(text("UPDATE audit_log SET created_at = created_at - interval '3 hours' WHERE action = 'platform.organization.created' AND created_at > now() - interval '2 hours'"))
    deps._TOKEN_LIMITERS.clear()
    yield
    deps._TOKEN_LIMITERS.clear()


@pytest.fixture
def two(client, make, migrated):
    op = make(operator=True)
    tok = _with_mfa_session(client, op)["access_token"]
    out = {"operator": {**op, "token": tok}}
    for k in ("a", "b"):
        r, _ = _post(client, tok)
        assert r.status_code == 201, r.text
        t = r.json()["tenant_id"]
        out[k] = {"id": t, "admin": make(role="isp_admin", tenant_id=t), "eng": make(role="engineer", tenant_id=t)}
        with migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t})
            e = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'tok-edge') RETURNING id"), {"t": t}).scalar()
            c.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor) VALUES (:t,:e,:n,'huawei')"), {"t": t, "e": e, "n": f"OLT-TOKEN-{k.upper()}"})
            c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'fleet_manager',true)"), {"t": t})
    return out


def _ah(client, org):
    return _h(_login(client, org["admin"])["access_token"])


def _create(client, org, perms=("inventory:read",), name="Integração NOC", days=30):
    r = client.post("/v1/api-tokens", json={"name": name, "permissions": list(perms), "days": days}, headers=_ah(client, org))
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_create_shows_the_secret_once_and_the_list_never_does(client, two, migrated):
    a = two["a"]
    made = _create(client, a, ("inventory:read", "fleet:read"))
    tok = made["token"]
    assert api_tokens.TOKEN_RE.match(tok) and made["prefix"] == tok[5:13] and made["permissions"] == ["fleet:read", "inventory:read"]
    lst = client.get("/v1/api-tokens", headers=_ah(client, a)).json()
    assert [i["id"] for i in lst["items"]] == [made["id"]] and "token" not in lst["items"][0] and tok not in str(lst)
    assert lst["items"][0]["state"] == "active" and lst["allowed_permissions"] == list(api_tokens.API_TOKEN_PERMISSIONS)
    with migrated.connect() as c:
        h = c.execute(text("SELECT token_hash FROM api_tokens WHERE id = :i"), {"i": made["id"]}).scalar()
        trail = str(c.execute(text("SELECT evidence_redacted FROM audit_log WHERE tenant_id = :t AND action = 'api_token.created'"), {"t": a["id"]}).all())
    assert bytes(h) == hashlib.sha256(tok.encode()).digest()                              # only the hash is stored
    assert tok not in trail and tok[13:] not in trail and made["prefix"] in trail          # the trail names the token by its prefix, never the secret


def test_only_an_administrator_manages_tokens_and_a_token_cannot_manage_tokens(client, two):
    a = two["a"]
    eng_h = _h(_login(client, a["eng"])["access_token"])
    assert client.get("/v1/api-tokens", headers=eng_h).status_code == 403
    assert client.post("/v1/api-tokens", json={"name": "Nao pode", "permissions": ["inventory:read"]}, headers=eng_h).status_code == 403
    tok = _create(client, a, ("inventory:read", "fleet:read"))["token"]
    for method, url, body in (("GET", "/v1/api-tokens", None), ("POST", "/v1/api-tokens", {"name": "Filho", "permissions": ["inventory:read"]}), ("DELETE", f"/v1/api-tokens/{uuid4()}", None)):
        assert client.request(method, url, json=body, headers=_bearer(tok)).status_code == 403, url


def test_the_permission_list_is_closed_and_read_only(client, two):
    a = two["a"]
    for bad in (["members:read"], ["audit:read"], ["customers:read"], ["fleet:manage"], ["jobs:request"], ["inventory:read", "inventory:write"], ["*"]):
        r = client.post("/v1/api-tokens", json={"name": "Token ruim", "permissions": bad}, headers=_ah(client, a))
        assert r.status_code == 422, (bad, r.text)
    for body in ({"name": "x", "permissions": ["inventory:read"]}, {"name": "Token ok", "permissions": []}, {"name": "Token ok", "permissions": ["inventory:read"], "days": 400},
                 {"name": "Token ok", "permissions": ["inventory:read"], "days": 0}):
        assert client.post("/v1/api-tokens", json=body, headers=_ah(client, a)).status_code == 422, body
    from app.core.permissions import CATALOG
    assert set(api_tokens.API_TOKEN_PERMISSIONS) <= set(CATALOG) and all(CATALOG[p].risk == "R0" for p in api_tokens.API_TOKEN_PERMISSIONS)   # every one is a plain read (R0)
    spec = importlib.util.spec_from_file_location("m0060", Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0060_api_tokens.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert tuple(m.ALLOWED) == api_tokens.API_TOKEN_PERMISSIONS                                                    # the database CHECK and the code list are the same


def test_a_token_reads_only_its_own_organization_and_only_what_it_was_given(client, two):
    a, b = two["a"], two["b"]
    ta = _create(client, a, ("inventory:read", "incidents:read"))["token"]
    tb = _create(client, b, ("fleet:read",))["token"]
    ra = client.get("/v1/olts", headers=_bearer(ta))
    assert ra.status_code == 200 and "OLT-TOKEN-A" in ra.text and "OLT-TOKEN-B" not in ra.text
    assert client.get("/v1/olts", headers={**_bearer(ta), "X-Workspace-Id": b["id"]}).text.count("OLT-TOKEN-B") == 0           # a header never picks another organization
    assert client.get("/v1/fleet/olts", headers=_bearer(ta)).status_code == 403                                               # not given `fleet:read`
    rb = client.get("/v1/fleet/olts", headers=_bearer(tb))
    assert rb.status_code == 200 and "OLT-TOKEN-B" in rb.text and "OLT-TOKEN-A" not in rb.text
    assert client.get("/v1/olts", headers=_bearer(tb)).status_code == 403
    for url in ("/v1/members", "/v1/audit", "/v1/team", "/v1/customers", "/v1/security-policy"):
        assert client.get(url, headers=_bearer(ta)).status_code in (403, 404), url
    assert client.post("/v1/fleet/olts", json={"name": "NOVA-TOKEN", "edge_id": str(uuid4()), "vendor": "huawei"}, headers=_bearer(tb)).status_code == 403   # nothing writes
    me = client.get("/v1/auth/me", headers=_bearer(ta)).json()
    assert me["kind"] == "api_token" and {p["name"] for p in me["permissions"]} == {"inventory:read", "incidents:read"} and me["tenant_id"] == a["id"]


def test_every_route_a_token_can_reach_is_a_read(client, two):
    """The closed list is read-only: no non-GET route may use one of its permissions (a new write route using one would break this)."""
    from app.core.rbac_matrix import inventory
    writes = [(r["method"], r["path"]) for r in inventory() if r["kind"] == "require" and set(r["permissions"]) & set(api_tokens.API_TOKEN_PERMISSIONS) and r["method"] != "GET"]
    assert not writes, writes


def test_revoked_expired_malformed_and_unknown_tokens_are_the_same_401(client, two, migrated):
    a = two["a"]
    made = _create(client, a)
    tok = made["token"]
    assert client.get("/v1/olts", headers=_bearer(tok)).status_code == 200
    assert client.delete(f"/v1/api-tokens/{made['id']}", headers=_ah(client, a)).json() == {"revoked": True}
    assert client.delete(f"/v1/api-tokens/{made['id']}", headers=_ah(client, a)).status_code == 404
    answers = {tuple(client.get("/v1/olts", headers=_bearer(x)).json().items()) for x in (tok, "fcat_short", "fcat_abcdefgh_" + "A" * 43, "fcat_" + "!" * 10, "not-a-jwt")}
    assert answers == {(("detail", "invalid or missing credentials"),)}                                           # no way to tell revoked from unknown from malformed
    live = _create(client, a, name="Para vencer")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a["id"]})
        c.execute(text("UPDATE api_tokens SET created_at = now() - interval '10 days', expires_at = now() - interval '1 day' WHERE id = :i"), {"i": live["id"]})
    assert client.get("/v1/olts", headers=_bearer(live["token"])).status_code == 401
    items = {i["id"]: i for i in client.get("/v1/api-tokens", headers=_ah(client, a)).json()["items"]}
    assert items[made["id"]]["state"] == "revoked" and items[live["id"]]["state"] == "expired"


def test_a_suspended_organization_closes_its_tokens_and_reactivation_reopens_them(client, two):
    a = two["a"]
    tok = _create(client, a)["token"]
    op = _h(two["operator"]["token"])
    assert client.post(f"/v1/platform/organizations/{a['id']}/status", json={"status": "suspended", "reason": "Teste de token"}, headers=op).status_code == 200
    r = client.get("/v1/olts", headers=_bearer(tok))
    assert r.status_code == 403 and r.json() == {"detail": "organization_suspended"}
    assert client.post(f"/v1/platform/organizations/{a['id']}/status", json={"status": "active", "reason": "Volta"}, headers=op).status_code == 200
    assert client.get("/v1/olts", headers=_bearer(tok)).status_code == 200


def test_a_token_has_its_own_rate_limit_and_the_organization_limit_of_active_tokens(client, two, monkeypatch):
    a = two["a"]
    tok = _create(client, a)["token"]
    monkeypatch.setattr(api_tokens, "DEFAULT_BURST", 2)
    monkeypatch.setattr(api_tokens, "DEFAULT_PER_MINUTE", 1)
    deps._TOKEN_LIMITERS.clear()
    codes = [client.get("/v1/olts", headers=_bearer(tok)).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    r = client.get("/v1/olts", headers=_bearer(tok))
    assert r.json() == {"detail": "token_rate_limited"} and int(r.headers["Retry-After"]) >= 1
    other = _create(client, a, name="Outro token")["token"]
    assert client.get("/v1/olts", headers=_bearer(other)).status_code == 200                                        # another token keeps its own budget
    monkeypatch.undo()
    for i in range(api_tokens.MAX_ACTIVE_PER_ORGANIZATION - 2):
        _create(client, a, name=f"Token {i:02d}")
    over = client.post("/v1/api-tokens", json={"name": "Passou", "permissions": ["inventory:read"]}, headers=_ah(client, a))
    assert over.status_code == 409 and over.json() == {"detail": "token_limit"}


def test_use_stamps_last_used_and_the_application_cannot_read_the_hash_or_change_a_token(client, two, app_engine):
    a = two["a"]
    made = _create(client, a)
    assert client.get("/v1/olts", headers=_bearer(made["token"])).status_code == 200
    items = client.get("/v1/api-tokens", headers=_ah(client, a)).json()["items"]
    assert items[0]["last_used_at"] is not None
    for sql in ("SELECT token_hash FROM api_tokens", "UPDATE api_tokens SET permissions = ARRAY['inventory:read']", "UPDATE api_tokens SET expires_at = now() + interval '300 days'", "DELETE FROM api_tokens"):
        with pytest.raises(ProgrammingError), app_engine.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a["id"])})
            c.execute(text(sql))
