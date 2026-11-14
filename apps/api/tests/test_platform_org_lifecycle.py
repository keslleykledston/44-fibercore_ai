"""Ciclo de vida da organização e console do operador (ADR-0047, fatia A): suspender/reativar com imposição real, renomear, flags pela tela, detalhe e histórico.

Provas: a suspensão fecha usuário E Edge daquela organização (e só dela), a reativação vale sem novo login; as funções do operador são o único caminho (a role da aplicação não tem
UPDATE em `tenants` nem escrita em `tenant_features`); motivo obrigatório, idempotência, par de auditoria; flags que escrevem na rede nunca ligam pela tela."""
from __future__ import annotations

import time
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core import features
from app.core.db import make_engine
from app.core.security import hash_secret, issue_token
from app.core.settings import get_settings
from tests.conftest import SECRET, hdr
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, role=None, tenant_id=None):
        email = f"l{uuid4().hex[:10]}@example.com"
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
    """The creation route allows 5 per hour across ALL actors: age what earlier tests left so every test here can create."""
    with migrated.begin() as c:
        c.execute(text("UPDATE audit_log SET created_at = created_at - interval '3 hours' WHERE action = 'platform.organization.created' AND created_at > now() - interval '2 hours'"))
    yield


@pytest.fixture
def org(client, operator, make, migrated):
    """A fresh organization created by the route, with an active isp_admin, an Edge and its service account. Returns ids and the admin's token."""
    r, body = _post(client, operator["token"])
    assert r.status_code == 201, r.text
    tid = r.json()["tenant_id"]
    admin = make(role="isp_admin", tenant_id=tid)
    with migrated.begin() as c:
        eid = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'life-edge') RETURNING id"), {"t": tid}).scalar()
        sa = c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,'life-agent','edge_agent',:h,:e) RETURNING id"),
                       {"t": tid, "h": hash_secret(SECRET), "e": eid}).scalar()
    return {"id": tid, "name": body["name"], "admin": admin, "edge": eid, "sa": sa, "operator": operator}


def _admin_h(client, org):
    return _h(_login(client, org["admin"])["access_token"])


def _edge_h(client, org):
    r = client.post("/v1/auth/service-token", json={"client_id": str(org["sa"]), "client_secret": SECRET})
    assert r.status_code == 200, r.text
    return _h(r.json()["access_token"])


def _set(client, org, status, reason="Teste do operador"):
    return client.post(f"/v1/platform/organizations/{org['id']}/status", json={"status": status, "reason": reason}, headers=_h(org["operator"]["token"]))


def _audit(migrated, tid, like):
    with migrated.connect() as c:
        return c.execute(text("SELECT action, evidence_redacted FROM audit_log WHERE tenant_id = :t AND action LIKE :l ORDER BY created_at, id"), {"t": tid, "l": like}).all()


# ============================================================ suspension is enforced
def test_suspension_closes_the_users_and_the_edge_of_that_organization_only_and_reactivation_reopens(client, org, make, migrated, seed):
    h_admin, h_edge = _admin_h(client, org), _edge_h(client, org)
    assert client.get("/v1/edges", headers=h_admin).status_code == 200
    assert client.get("/v1/members", headers=h_admin).status_code == 200
    other = hdr(client, "bob", seed, "B")
    assert client.get("/v1/edges", headers=other).status_code == 200

    r = _set(client, org, "suspended", "Contrato encerrado")
    assert r.status_code == 200 and r.json()["changed"] is True and r.json()["status"] == "suspended"

    for url in ("/v1/edges", "/v1/members", "/v1/auth/me"):
        g = client.get(url, headers=h_admin)
        assert g.status_code == 403 and g.json() == {"detail": "organization_suspended"}, url
    hb = client.post("/v1/edge/heartbeat", json={"version": "x"}, headers=h_edge)
    assert hb.status_code == 403 and hb.json() == {"detail": "organization_suspended"}      # the Edge's own account is closed too
    assert client.get("/v1/edges", headers=other).status_code == 200                       # nobody else is touched
    ws = client.get("/v1/auth/workspaces", headers=h_admin).json()
    assert [w["suspended"] for w in ws if w["tenant_id"] == str(org["id"])] == [True]       # the list shows it, flagged (the person learns why nothing opens)

    assert _set(client, org, "active", "Voltou a pagar").json() == {"changed": True, "status": "active", "previous": "suspended"}
    assert client.get("/v1/edges", headers=h_admin).status_code == 200                      # same tokens, no new login
    assert [w["suspended"] for w in client.get("/v1/auth/workspaces", headers=h_admin).json() if w["tenant_id"] == str(org["id"])] == [False]
    assert client.post("/v1/edge/heartbeat", json={"version": "x"}, headers=h_edge).status_code != 403


def test_suspension_is_idempotent_and_audited_in_pairs(client, org, migrated):
    assert _set(client, org, "suspended", "Primeira vez").json()["changed"] is True
    again = _set(client, org, "suspended", "Segunda vez")
    assert again.status_code == 200 and again.json() == {"changed": False, "status": "suspended"}
    done = _audit(migrated, org["id"], "platform.organization.suspended")
    assert len(done) == 1 and done[0].evidence_redacted["reason"] == "Primeira vez" and done[0].evidence_redacted["from"] == "active" and done[0].evidence_redacted["to"] == "suspended"
    rid = done[0].evidence_redacted["request_id"]
    pairs = [e for _, e in _audit(migrated, org["id"], "platform.change.requested")]
    assert rid in [e["request_id"] for e in pairs] and all(e["route"].startswith("POST /v1/platform/organizations/") for e in pairs)
    _set(client, org, "active", "Reativada")
    assert len(_audit(migrated, org["id"], "platform.organization.reactivated")) == 1


@pytest.mark.parametrize("reason", ["ab", "  ", "x" * 201, "com\x07controle"])
def test_the_reason_is_required_and_bounded(client, org, reason):
    r = _set(client, org, "suspended", reason)
    assert r.status_code == 422 and r.json() == {"detail": "organization_reason_invalid"}
    assert client.get("/v1/edges", headers=_admin_h(client, org)).status_code == 200    # nothing was suspended


def test_bad_status_unknown_org_and_non_operator(client, org, make, operator):
    assert client.post(f"/v1/platform/organizations/{org['id']}/status", json={"status": "closed", "reason": "teste"}, headers=_h(operator["token"])).status_code == 422
    assert _set(client, {**org, "id": uuid4()}, "suspended").status_code == 404
    h_admin = _admin_h(client, org)                              # before the MFA enrolment (after it the account logs in in two steps)
    admin_session = _with_mfa_session(client, org["admin"])      # an isp_admin WITH a recent second factor still has no way in
    for call in (lambda: client.post(f"/v1/platform/organizations/{org['id']}/status", json={"status": "suspended", "reason": "teste"}, headers=_h(admin_session["access_token"])),
                 lambda: client.post(f"/v1/platform/organizations/{org['id']}/rename", json={"name": "Novo"}, headers=_h(admin_session["access_token"])),
                 lambda: client.put(f"/v1/platform/organizations/{org['id']}/features/onu_discovery", json={"state": "on", "reason": "teste"}, headers=_h(admin_session["access_token"])),
                 lambda: client.get(f"/v1/platform/organizations/{org['id']}", headers=_h(admin_session["access_token"]))):
        assert call().status_code == 403
    assert client.get("/v1/edges", headers=h_admin).status_code == 200


def test_an_operator_without_a_recent_second_factor_cannot_change_anything(client, org, operator):
    old = issue_token(get_settings(), sub=operator["id"], kind="user", mfa_at=time.time() - 3600)
    r = client.post(f"/v1/platform/organizations/{org['id']}/status", json={"status": "suspended", "reason": "sem mfa"}, headers=_h(old))
    assert r.status_code == 403 and r.json() == {"detail": "mfa_recent_required"}


def test_the_application_role_cannot_write_tenants_or_flags_and_the_function_rechecks_the_actor(app_engine, org, make):
    with pytest.raises((ProgrammingError, DBAPIError)):
        with app_engine.begin() as c:
            c.execute(text("UPDATE tenants SET status = 'suspended' WHERE id = :t"), {"t": org["id"]})
    with pytest.raises((ProgrammingError, DBAPIError)):
        with app_engine.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
            c.execute(text("INSERT INTO tenant_features(tenant_id, feature, enabled) VALUES (:t, 'onu_discovery', true)"), {"t": org["id"]})
    plain = make()          # not an operator
    for sql in ("SELECT public.platform_set_organization_status(:a, :t, 'suspended', 'teste ok', :r)", "SELECT public.platform_rename_organization(:a, :t, 'Outro Nome', :r)",
                "SELECT public.platform_set_feature(:a, :t, 'onu_discovery', 'on', 'teste ok', :r)", "SELECT public.platform_organization_detail(:a, :t)"):
        with pytest.raises(DBAPIError) as ei:
            with app_engine.begin() as c:
                c.execute(text(sql), {"a": plain["id"], "t": org["id"], "r": uuid4()})
        assert "platform_forbidden" in str(ei.value)


# ============================================================ rename
def test_rename_rules_and_audit(client, org, operator, migrated):
    h = _h(operator["token"])
    r = client.post(f"/v1/platform/organizations/{org['id']}/rename", json={"name": "  Provedor   Novo "}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Provedor Novo" and r.json()["changed"] is True
    assert client.post(f"/v1/platform/organizations/{org['id']}/rename", json={"name": "Provedor Novo"}, headers=h).json()["changed"] is False
    other, body = _post(client, operator["token"])
    assert other.status_code == 201
    taken = client.post(f"/v1/platform/organizations/{org['id']}/rename", json={"name": body["name"].upper()}, headers=h)
    assert taken.status_code == 409 and taken.json() == {"detail": "organization_name_taken"}
    assert client.post(f"/v1/platform/organizations/{org['id']}/rename", json={"name": "x"}, headers=h).status_code == 422
    rows = _audit(migrated, org["id"], "platform.organization.renamed")
    assert len(rows) == 1 and rows[0].evidence_redacted["to"] == "Provedor Novo" and rows[0].evidence_redacted["from"] == org["name"]


# ============================================================ flags by screen
def _feature(client, org, name, state, reason="Ligado no piloto", token=None):
    return client.put(f"/v1/platform/organizations/{org['id']}/features/{name}", json={"state": state, "reason": reason}, headers=_h(token or org["operator"]["token"]))


def test_a_flag_is_switched_on_off_and_back_to_default_with_audit(client, org, migrated):
    r = _feature(client, org, "onu_discovery", "on")
    assert r.status_code == 200 and r.json() == {"changed": True, "state": "on", "previous": "default"}
    with migrated.begin() as c:
        assert features.enabled(c, org["id"], "onu_discovery") is True
    assert _feature(client, org, "onu_discovery", "on").json()["changed"] is False
    assert _feature(client, org, "onu_discovery", "off").json() == {"changed": True, "state": "off", "previous": "on"}
    assert _feature(client, org, "onu_discovery", "default").json() == {"changed": True, "state": "default", "previous": "off"}
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM tenant_features WHERE tenant_id = :t"), {"t": org["id"]}).scalar() == 0
    ev = [e for _, e in _audit(migrated, org["id"], "platform.feature.set")]
    assert [(e["feature"], e["from"], e["to"]) for e in ev] == [("onu_discovery", "default", "on"), ("onu_discovery", "on", "off"), ("onu_discovery", "off", "default")]
    assert all(e["reason"] == "Ligado no piloto" for e in ev)


def test_flag_validation_owner_only_and_preconditions(client, org, migrated, monkeypatch):
    assert _feature(client, org, "no_such_flag", "on").status_code == 422
    assert _feature(client, org, "onu_discovery", "maybe").status_code == 422
    assert _feature(client, org, "onu_discovery", "on", reason="ab").status_code == 422
    for name in ("bench_writes", "smart_diagnostics_active_tests", "smart_diagnostics_remediation", "quality_active_tests", "smart_diagnostics_copilot"):
        r = _feature(client, org, name, "on")
        assert r.status_code == 403 and r.json() == {"detail": "owner_only_feature"}, name
    with migrated.begin() as c:     # the owner turned one on from the CLI; the screen may turn it OFF (and back to default), never on
        c.execute(text("INSERT INTO tenant_features(tenant_id, feature, enabled) VALUES (:t, 'quality_active_tests', true)"), {"t": org["id"]})
    assert _feature(client, org, "quality_active_tests", "off").json() == {"changed": True, "state": "off", "previous": "on"}
    from app.core import olt_query
    monkeypatch.setattr(olt_query, "EDGE_SUPPORT", False)
    r = _feature(client, org, "olt_query", "on")
    assert r.status_code == 422 and r.json() == {"detail": "feature_precondition"}
    assert _feature(client, org, "olt_query", "off").status_code == 200        # turning off is never blocked
    with migrated.begin() as c:
        assert not features.enabled(c, org["id"], "olt_query")


# ============================================================ detail, history, list
def test_detail_shows_state_health_flags_and_a_whitelisted_history(client, org, operator, migrated):
    h = _h(operator["token"])
    _feature(client, org, "onu_discovery", "on")
    _set(client, org, "suspended", "Teste de histórico")
    d = client.get(f"/v1/platform/organizations/{org['id']}", headers=h)
    assert d.status_code == 200 and d.headers["Cache-Control"] == "no-store"
    j = d.json()
    assert j["status"] == "suspended" and j["name"] == org["name"] and j["edges"] == 1 and j["edges_online"] == 0 and j["flags_on"] == 1
    cat = {c["feature"]: c for c in j["catalog"]}
    assert cat["onu_discovery"]["enabled"] is True and cat["onu_discovery"]["source"] == "tenant" and cat["bench_writes"]["owner_only"] is True
    actions = [x["action"] for x in j["history"]]
    assert actions[:2] == ["platform.organization.suspended", "platform.feature.set"] and "platform.organization.created" in actions
    allowed = {"reason", "from", "to", "feature", "name"}
    assert all(set(x["detail"]) <= allowed for x in j["history"])
    assert "@" not in str(j["history"])                                  # the masked admin e-mail of the creation never leaves the trail
    assert client.get(f"/v1/platform/organizations/{uuid4()}", headers=h).status_code == 404


def test_the_list_carries_health_and_state(client, org, operator, migrated):
    with migrated.begin() as c:
        c.execute(text("UPDATE edges SET last_heartbeat_at = now() WHERE id = :e"), {"e": org["edge"]})
    j = client.get("/v1/platform/organizations?limit=200", headers=_h(operator["token"])).json()
    row = next(i for i in j["items"] if i["id"] == str(org["id"]))
    assert row["status"] == "active" and row["edges_total"] == 1 and row["edges_online"] == 1 and row["olts_stale"] == 0 and row["last_heartbeat_at"] and row["flags_on"] == 0
    assert set(row) >= {"edges", "olts", "onus", "edges_online", "edges_total", "olts_stale", "last_heartbeat_at", "flags_on", "status"}
    with migrated.begin() as c:
        c.execute(text("UPDATE edges SET last_heartbeat_at = now() - interval '10 minutes' WHERE id = :e"), {"e": org["edge"]})
    row = next(i for i in client.get("/v1/platform/organizations?limit=200", headers=_h(operator["token"])).json()["items"] if i["id"] == str(org["id"]))
    assert row["edges_online"] == 0 and row["edges_total"] == 1


def test_the_database_itself_refuses_to_turn_owner_only_flags_on_and_the_two_lists_agree(client, org, operator, app_engine):
    """Codex r1 HIGH: the route is not the only gate. A direct call of the function by an ACTIVE operator (the actor the application role may pick, R-3) is refused for the same names."""
    import importlib.util
    import pathlib

    from app.api.platform_orgs import OWNER_ONLY_FEATURES
    spec = importlib.util.spec_from_file_location("m0054", pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0054_platform_org_lifecycle.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert set(mod.OWNER_ONLY) == set(OWNER_ONLY_FEATURES)
    for name in sorted(OWNER_ONLY_FEATURES):
        with pytest.raises(DBAPIError) as ei:
            with app_engine.begin() as c:
                c.execute(text("SELECT public.platform_set_feature(:a, :t, :f, 'on', 'teste direto', :r)"), {"a": operator["id"], "t": org["id"], "f": name, "r": uuid4()})
        assert "owner_only_feature" in str(ei.value), name
    with app_engine.begin() as c:     # turning it OFF, and any other flag ON, still work through the function
        r = c.execute(text("SELECT public.platform_set_feature(:a, :t, 'onu_discovery', 'on', 'teste direto', :r)"), {"a": operator["id"], "t": org["id"], "r": uuid4()}).scalar_one()
    assert r["changed"] is True


def test_the_cli_org_status_break_glass_suspends_reactivates_and_audits(client, org, migrated, admin_url, monkeypatch):
    """Regression: the CLI's audit INSERT used one parameter as uuid and as text (it failed on the first real use). Break-glass must work and leave the trail."""
    from app import cli
    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(org["id"])
    cli.main(["org-status", t, "suspended", "--reason", "Quebra-vidro de teste"])
    assert client.get("/v1/edges", headers=_admin_h(client, org)).status_code == 403
    cli.main(["org-status", t, "suspended", "--reason", "De novo, nada muda"])            # idempotent: no second trail entry
    cli.main(["org-status", t, "active", "--reason", "Quebra-vidro encerrado"])
    assert client.get("/v1/edges", headers=_admin_h(client, org)).status_code == 200
    sus, rea = _audit(migrated, org["id"], "platform.organization.suspended"), _audit(migrated, org["id"], "platform.organization.reactivated")
    assert len(sus) == 1 and len(rea) == 1 and sus[0][1]["via"] == "cli" and sus[0][1]["reason"] == "Quebra-vidro de teste"
    with pytest.raises(SystemExit, match="no such organization"):
        cli.main(["org-status", str(uuid4()), "active", "--reason", "organização inexistente"])
