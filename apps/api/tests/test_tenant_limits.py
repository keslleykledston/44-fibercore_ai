"""Limites técnicos por organização (ADR-0047 D3, fatia B): padrão no código, ajuste só pelo operador, 409 `limit_reached` ao criar (OLT pela tela e pelo Edge, Edge e membro pela CLI),
nada existente é tocado, orçamento de ingestão por organização. Sem plano, sem preço."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core import limits
from app.core.db import make_engine
from app.core.security import hash_secret
from tests.conftest import SECRET
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, role=None, tenant_id=None):
        email = f"m{uuid4().hex[:10]}@example.com"
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


@pytest.fixture
def org(client, operator, make, migrated):
    r, body = _post(client, operator["token"])
    assert r.status_code == 201, r.text
    tid = r.json()["tenant_id"]
    admin = make(role="isp_admin", tenant_id=tid)
    with migrated.begin() as c:
        eid = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'lim-edge') RETURNING id"), {"t": tid}).scalar()
        sa = c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,'lim-agent','edge_agent',:h,:e) RETURNING id"),
                       {"t": tid, "h": hash_secret(SECRET), "e": eid}).scalar()
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'fleet_manager',true)"), {"t": tid})
    return {"id": tid, "admin": admin, "edge": eid, "sa": sa, "operator": operator}


def _put(client, org, limits_body, reason="Ajuste de teste"):
    return client.put(f"/v1/platform/organizations/{org['id']}/limits", json={"limits": limits_body, "reason": reason}, headers=_h(org["operator"]["token"]))


def _detail(client, org):
    r = client.get(f"/v1/platform/organizations/{org['id']}", headers=_h(org["operator"]["token"]))
    assert r.status_code == 200, r.text
    return r.json()


def _admin_h(client, org):
    return _h(_login(client, org["admin"])["access_token"])


def _edge_h(client, org):
    r = client.post("/v1/auth/service-token", json={"client_id": str(org["sa"]), "client_secret": SECRET})
    assert r.status_code == 200, r.text
    return _h(r.json()["access_token"])


def _olt_body(org, name):
    return {"name": name, "edge_id": str(org["edge"]), "vendor": "huawei"}


def _snapshot(org, name):
    return {"edge_id": str(org["edge"]), "observed_at": datetime.now(UTC).isoformat(), "name": name, "vendor": "huawei"}


# ============================================================ defaults, set, clear
def test_the_detail_shows_the_code_defaults_the_usage_and_no_override(client, org):
    lim = _detail(client, org)["limits"]
    s = limits.defaults()
    assert lim["values"] == {"max_edges": None, "max_olts": None, "max_members": None, "ingest_per_minute": None, "ingest_burst": None}
    assert lim["defaults"] == s and lim["effective"] == s
    assert lim["usage"] == {"edges": 1, "olts": 0, "members": 1, "invites_open": 1}   # the first-administrator invite of the creation is still open


def test_set_clear_idempotent_audited_in_pairs_and_visible_in_the_history(client, org, migrated):
    r = _put(client, org, {"max_olts": 3, "max_members": 5})
    assert r.status_code == 200 and r.json()["changed"] is True
    assert r.json()["limits"]["max_olts"] == 3 and r.json()["limits"]["max_edges"] is None
    assert _put(client, org, {"max_olts": 3}).json() == {"changed": False, "limits": r.json()["limits"]}
    d = _detail(client, org)
    assert d["limits"]["effective"]["max_olts"] == 3 and d["limits"]["effective"]["max_edges"] == limits.defaults()["max_edges"]
    acts = [h["action"] for h in d["history"]]
    assert acts.count("platform.limits.set") == 1
    back = _put(client, org, {"max_olts": None})
    assert back.json()["changed"] is True and back.json()["limits"]["max_olts"] is None
    with migrated.connect() as c:
        done = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE tenant_id = :t AND action = 'platform.limits.set' ORDER BY created_at, id"), {"t": org["id"]}).all()
        asked = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE tenant_id = :t AND action = 'platform.change.requested' AND evidence_redacted ->> 'kind' = 'limits'"),
                          {"t": org["id"]}).all()
    assert len(done) == 2 and len(asked) == 3          # the idempotent call also writes the route's half (the same as the status route)
    assert {str(e[0]["request_id"]) for e in done} <= {e[0]["request_id"] for e in asked}
    assert done[0][0]["from"]["max_olts"] is None and done[0][0]["to"]["max_olts"] == 3 and done[0][0]["reason"] == "Ajuste de teste"


@pytest.mark.parametrize("body", [{}, {"max_olts": -1}, {"max_olts": 100001}, {"max_edges": 10001}, {"ingest_per_minute": 0}, {"ingest_burst": 10001}, {"made_up": 1}, {"max_olts": "7"}, {"max_olts": 1.5},
                                  {"max_olts": True}])
def test_invalid_limits_are_refused(client, org, body):
    r = _put(client, org, body)
    assert r.status_code == 422, (body, r.text)


def test_the_database_refuses_what_the_route_would_not_check(client, org, operator, migrated, app_engine):
    # the function is the last word: ranges and keys are checked there too (called directly, as the application role)
    with pytest.raises(DBAPIError) as e, app_engine.begin() as c:
        c.execute(text("SELECT public.platform_set_limits(:a, :t, CAST(:l AS jsonb), 'teste direto', :r)"), {"a": operator["id"], "t": org["id"], "l": '{"max_olts": -5}', "r": uuid4()})
    assert "limits_invalid" in str(e.value)
    with pytest.raises(DBAPIError) as e2, app_engine.begin() as c:
        c.execute(text("SELECT public.platform_set_limits(:a, :t, CAST(:l AS jsonb), 'teste direto', :r)"), {"a": operator["id"], "t": org["id"], "l": '{"x": 1}', "r": uuid4()})
    assert "limits_invalid" in str(e2.value)


def test_reason_is_required_and_only_the_operator_can_change(client, org, make):
    assert _put(client, org, {"max_olts": 4}, reason="  ").status_code == 422
    assert client.put(f"/v1/platform/organizations/{org['id']}/limits", json={"limits": {"max_olts": 4}, "reason": "ok ok"}, headers=_admin_h(client, org)).status_code == 403
    other = make(operator=False)
    tok = _login(client, other)["access_token"]
    assert client.put(f"/v1/platform/organizations/{org['id']}/limits", json={"limits": {"max_olts": 4}, "reason": "ok ok"}, headers=_h(tok)).status_code == 403
    assert _put(client, {**org, "id": str(uuid4())}, {"max_olts": 4}).status_code == 404


def test_the_application_role_cannot_write_the_table_only_the_function_can(org, app_engine):
    for sql in ("INSERT INTO tenant_limits (tenant_id, max_olts) VALUES (:t, 1)", "UPDATE tenant_limits SET max_olts = 1", "DELETE FROM tenant_limits"):
        with pytest.raises(ProgrammingError), app_engine.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
            c.execute(text(sql), {"t": org["id"]})


def test_an_organization_reads_only_its_own_row(client, org, seed, migrated, app_engine):
    assert _put(client, org, {"max_olts": 9}).status_code == 200
    with app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert c.execute(text("SELECT count(*) FROM tenant_limits WHERE tenant_id = :t"), {"t": org["id"]}).scalar() == 0
        assert limits.effective(c, UUID(str(org["id"])))["max_olts"] == limits.defaults()["max_olts"]   # sees no row of another organization: the default


# ============================================================ enforcement
def test_registering_an_olt_over_the_limit_is_409_and_nothing_existing_is_touched(client, org, migrated):
    h = _admin_h(client, org)
    assert _put(client, org, {"max_olts": 1}).status_code == 200
    ok = client.post("/v1/fleet/olts", json=_olt_body(org, "LIM-OLT-1"), headers=h)
    assert ok.status_code == 201, ok.text
    over = client.post("/v1/fleet/olts", json=_olt_body(org, "LIM-OLT-2"), headers=h)
    assert over.status_code == 409 and over.json() == {"detail": "limit_reached"}
    assert (over.headers["X-Limit-Resource"], over.headers["X-Limit-Max"], over.headers["X-Limit-Current"]) == ("olts", "1", "1")
    assert _detail(client, org)["limits"]["usage"]["olts"] == 1
    # lowering BELOW the use removes nothing and blocks nothing that exists
    assert _put(client, org, {"max_olts": 0}).status_code == 200
    assert client.get("/v1/fleet/olts", headers=h).status_code == 200
    assert _detail(client, org)["limits"]["usage"]["olts"] == 1
    assert client.post("/v1/fleet/olts", json=_olt_body(org, "LIM-OLT-3"), headers=h).status_code == 409
    # raising it again reopens
    assert _put(client, org, {"max_olts": None}).status_code == 200
    assert client.post("/v1/fleet/olts", json=_olt_body(org, "LIM-OLT-3"), headers=h).status_code == 201


def test_the_edge_inventory_limit_counts_only_a_new_olt(client, org):
    he = _edge_h(client, org)
    assert _put(client, org, {"max_olts": 1}).status_code == 200
    assert client.post("/v1/edge/olt-snapshots", json=_snapshot(org, "LIM-SNAP-1"), headers=he).status_code == 202
    again = client.post("/v1/edge/olt-snapshots", json=_snapshot(org, "LIM-SNAP-1"), headers=he)
    assert again.status_code == 202                              # an OLT already known keeps reporting, whatever the limit
    new = client.post("/v1/edge/olt-snapshots", json=_snapshot(org, "LIM-SNAP-2"), headers=he)
    assert new.status_code == 409 and new.json() == {"detail": "limit_reached"}


def test_an_organization_over_its_limit_does_not_affect_another(client, org, seed, inv, migrated):
    assert _put(client, org, {"max_olts": 0}).status_code == 200
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'fleet_manager',true) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = true"), {"t": seed["A"]})
    from tests.conftest import hdr
    h = hdr(client, "alice", seed, "A")
    r = client.post("/v1/fleet/olts", json={"name": "LIM-A-1", "edge_id": str(inv["a1"]["edge"]), "vendor": "huawei"}, headers=h)
    assert r.status_code == 201, r.text
    with migrated.begin() as c:
        c.execute(text("DELETE FROM olts WHERE name = 'LIM-A-1'"))


def test_invites_count_as_reserved_seats_and_a_replaced_invite_is_not_counted_twice(client, org):
    h = _admin_h(client, org)
    assert _detail(client, org)["limits"]["usage"]["members"] == 1      # + the creation's first-administrator invite (open) = 2 seats in use
    assert _put(client, org, {"max_members": 3}).status_code == 200
    first = client.post("/v1/team/invites", json={"email": "ana.limite@example.com", "role": "support"}, headers=h)
    assert first.status_code == 201, first.text
    assert _detail(client, org)["limits"]["usage"]["invites_open"] == 2
    other = client.post("/v1/team/invites", json={"email": "bia.limite@example.com", "role": "support"}, headers=h)
    assert other.status_code == 409 and other.json() == {"detail": "limit_reached"} and other.headers["X-Limit-Resource"] == "members"
    again = client.post("/v1/team/invites", json={"email": "ANA.limite@example.com", "role": "engineer"}, headers=h)   # replaces the first: still one seat
    assert again.status_code == 201, again.text
    renewed = client.post(f"/v1/team/invites/{again.json()['id']}/renew", headers=h)
    assert renewed.status_code == 201, renewed.text
    assert client.delete(f"/v1/team/invites/{renewed.json()['id']}", headers=h).status_code == 200
    assert client.post("/v1/team/invites", json={"email": "bia.limite@example.com", "role": "support"}, headers=h).status_code == 201


def test_the_cli_obeys_the_same_limits_for_edges_and_members(org, migrated, admin_url, monkeypatch):
    from app import cli
    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(org["id"])
    cli.main(["limits-set", t, "--max-edges", "1", "--max-members", "1", "--reason", "Piloto pequeno"])
    with pytest.raises(SystemExit, match="limit_reached: edges 1/1"):
        cli.main(["register-edge", t, "second-edge"])
    extra = f"x{uuid4().hex[:8]}@example.com"
    with migrated.begin() as c:
        c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,'Extra',:h)"), {"e": extra, "h": hash_secret(PW)})
    with pytest.raises(SystemExit, match="limit_reached: members 2/1"):
        cli.main(["add-member", t, extra, "support"])
    cli.main(["limits-set", t, "--max-edges", "default", "--max-members", "default", "--reason", "Voltou ao padrão"])
    cli.main(["register-edge", t, "second-edge"])
    with migrated.connect() as c:
        row = c.execute(text("SELECT max_edges, max_members FROM tenant_limits WHERE tenant_id = :t"), {"t": org["id"]}).one()
        assert tuple(row) == (None, None)
        trail = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE tenant_id = :t AND action = 'platform.limits.set' ORDER BY created_at, id"), {"t": org["id"]}).all()
    assert len(trail) == 2 and trail[0][0]["via"] == "cli" and trail[0][0]["reason"] == "Piloto pequeno"
    with pytest.raises(SystemExit, match="nothing to set"):
        cli.main(["limits-set", t, "--reason", "nada a mudar"])
    with pytest.raises(SystemExit, match="integer between"):
        cli.main(["limits-set", t, "--max-olts", "-3", "--reason", "valor ruim"])


def test_concurrent_creations_cannot_pass_the_maximum(org, migrated):
    """The decision runs under an advisory lock per (organization, resource): two transactions race, only one fits."""
    import threading
    assert limits.RESOURCES["olts"]
    with migrated.begin() as c:
        c.execute(text("INSERT INTO tenant_limits (tenant_id, max_olts) VALUES (:t, 1)"), {"t": org["id"]})
    results: list[str] = []

    def worker(i: int) -> None:
        try:
            with migrated.begin() as c:
                c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
                limits.check_capacity(c, UUID(str(org["id"])), "olts")
                c.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level) VALUES (:t,:e,:n,'huawei','identified')"), {"t": org["id"], "e": org["edge"], "n": f"LIM-RACE-{i}"})
            results.append("ok")
        except limits.LimitReached:
            results.append("limit")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["limit", "limit", "limit", "ok"], results


# ============================================================ intake budget per organization
def test_the_intake_budget_of_the_organization_is_enforced_across_all_its_agents(client, org):
    from app.api import deps
    deps._INGEST_LIMITERS.clear()
    deps._ORG_BUDGETS.clear()
    try:
        assert _put(client, org, {"ingest_burst": 2, "ingest_per_minute": 1}).status_code == 200
        he = {**_edge_h(client, org), deps.EDGE_BACKOFF_HEADER: "retry-after"}   # only an Edge that says it understands 429 is limited (version skew rule)
        codes = [client.post("/v1/edge/olt-snapshots", json=_snapshot(org, f"LIM-RATE-{i}"), headers=he).status_code for i in range(4)]
        assert codes[:2] == [202, 202] and codes[2:] == [429, 429], codes
        r = client.post("/v1/edge/olt-snapshots", json=_snapshot(org, "LIM-RATE-9"), headers=he)
        assert r.status_code == 429 and r.json() == {"detail": "organization_rate_limited"} and int(r.headers["Retry-After"]) >= 1
        # an Edge that does not announce 429 support is never limited, org budget included
        old = _edge_h(client, org)
        assert client.post("/v1/edge/olt-snapshots", json=_snapshot(org, "LIM-RATE-8"), headers=old).status_code == 202
    finally:
        deps._INGEST_LIMITERS.clear()
        deps._ORG_BUDGETS.clear()
