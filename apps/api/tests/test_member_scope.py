"""Escopo por site/OLT (ADR-0049 D2, cumpre o ADR-0031 item 3): o recorte é um predicado de RLS, não um filtro de tela.

Provas: quem pode atribuir (e a quem); listas, contagens e detalhes do principal com escopo só mostram o que está nele; o que está fora responde como se não existisse (404/lista vazia);
permissões não escopáveis (clientes, membros, auditoria, escrita) ficam fechadas; mudança de escopo vale sem novo login; escopo vazio vê NADA (nunca tudo); inventário obrigatório do ADR-0031:
TODA rota de leitura alcançável por um principal com escopo é percorrida com dados de fora do escopo semeados e nenhum deles aparece, e TODA tabela de dados é classificada (nova tabela sem
classificação quebra o teste)."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core import scope as scope_mod
from app.core.db import make_engine
from app.core.rbac_matrix import inventory
from app.core.security import hash_secret
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session

NOW = datetime.now(UTC)


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, role=None, tenant_id=None):
        email = f"s{uuid4().hex[:10]}@example.com"
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
    yield


@pytest.fixture
def world(client, make, migrated):
    """An organization with two sites of OLTs (A: two OLTs, B: one), a third empty site, ONUs, CPEs (linked and not), incidents and the people: an administrator, scoped engineers and a free one."""
    op = make(operator=True)
    tok = _with_mfa_session(client, op)["access_token"]
    r, _ = _post(client, tok)
    assert r.status_code == 201, r.text
    t = r.json()["tenant_id"]
    w: dict = {"t": t, "admin": make(role="isp_admin", tenant_id=t), "eng_a": make(role="engineer", tenant_id=t), "eng_b": make(role="engineer", tenant_id=t),
               "eng_empty": make(role="noc_n2", tenant_id=t), "eng_free": make(role="engineer", tenant_id=t), "support": make(role="support", tenant_id=t)}
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'fleet_manager',true)"), {"t": t})
        e = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'scope-edge') RETURNING id"), {"t": t}).scalar()
        pop = {k: c.execute(text("INSERT INTO pops (tenant_id, name) VALUES (:t,:n) RETURNING id"), {"t": t, "n": n}).scalar() for k, n in (("A", "SITE-A-OK"), ("B", "SITE-B-SECRETO"), ("C", "SITE-C-VAZIO"))}
        olt, onu, pon = {}, {}, {}
        for k, name, p in (("A1", "OLT-A1-OK", "A"), ("A2", "OLT-A2-OK", "A"), ("B1", "OLT-B1-SECRETA", "B")):
            olt[k] = c.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, pop_id) VALUES (:t,:e,:n,'huawei',:p) RETURNING id"), {"t": t, "e": e, "n": name, "p": pop[p]}).scalar()
            pon[k] = c.execute(text("INSERT INTO pon_ports (tenant_id, olt_id, pon_path) VALUES (:t,:o,'0/1/0') RETURNING id"), {"t": t, "o": olt[k]}).scalar()
            for i in (1, 2):
                onu[f"{k}-{i}"] = c.execute(text("INSERT INTO onus (tenant_id, olt_id, pon_id, serial, status) VALUES (:t,:o,:p,:s,'offline') RETURNING id"),
                                            {"t": t, "o": olt[k], "p": pon[k], "s": f"SER{k}{i:02d}{'SECRETA' if k == 'B1' else 'OK'}"}).scalar()
        cpe = {k: c.execute(text("INSERT INTO cpes (tenant_id, edge_id, canonical_serial) VALUES (:t,:e,:s) RETURNING id"), {"t": t, "e": e, "s": f"CPE{k}{'SECRETA' if k == 'B' else 'OK'}"}).scalar()
               for k in ("A", "B", "X")}
        for k, o in (("A", "A1-1"), ("B", "B1-1")):
            c.execute(text("INSERT INTO onu_cpe_links (tenant_id, onu_id, cpe_id, status, confidence, evidence, reviewed_by, reviewed_at) VALUES (:t,:u,:c,'confirmed',0.9,CAST('{\"rule\":\"test\"}' AS jsonb),:r,now())"),
                      {"t": t, "u": onu[o], "c": cpe[k], "r": uuid4()})
        inc = {}
        for k in ("A1", "B1"):
            inc[k] = c.execute(text("INSERT INTO incidents(tenant_id, kind, olt_id, pon_id, dedupe_key, suspected_cause, evidence) VALUES (:t,'pon_mass_outage',:o,:p,:d,'power',CAST('{}' AS jsonb)) RETURNING id"),
                               {"t": t, "o": olt[k], "p": pon[k], "d": f"dk-{k}-{'SECRETO' if k == 'B1' else 'ok'}"}).scalar()
            c.execute(text("INSERT INTO incident_onus(tenant_id, incident_id, onu_id) VALUES (:t,:i,:u)"), {"t": t, "i": inc[k], "u": onu[f"{k}-1"]})
        for k in ("A1-1", "B1-1"):
            c.execute(text("INSERT INTO onu_state_events (tenant_id, onu_id, olt_id, serial, to_status, at) VALUES (:t,:u,:o,:s,'offline',:at)"),
                      {"t": t, "u": onu[k], "o": olt[k.split("-")[0]], "s": f"EV{k}{'SECRETO' if k.startswith('B') else 'ok'}", "at": NOW})
    w.update(edge=e, pop=pop, olt=olt, onu=onu, pon=pon, cpe=cpe, inc=inc)
    # the people: scope by the administrator, through the route (the real path)
    h = _h(_login(client, w["admin"])["access_token"])
    for who, body in (("eng_a", {"pop_ids": [str(pop["A"])]}), ("eng_b", {"olt_ids": [str(olt["B1"])]}), ("eng_empty", {"pop_ids": [str(pop["C"])]}), ("support", {"pop_ids": [str(pop["A"])]})):
        r = client.put(f"/v1/team/members/{w[who]['id']}/scope", json=body, headers=h)
        assert r.status_code == 200, (who, r.text)
    w["h_admin"] = h
    return w


def _as(client, who):
    return _h(_login(client, who)["access_token"])


def _ids(rows, key="id"):
    return {str(x[key]) for x in rows}


SECRETS_RE = re.compile(r"SECRET[OA]|SITE-B|OLT-B1|dk-B1|EVB1", re.I)


# ============================================================ assigning
def test_only_an_administrator_assigns_and_only_to_a_member_who_can_carry_it(client, world):
    w, h = world, world["h_admin"]
    pa = str(w["pop"]["A"])
    assert client.put(f"/v1/team/members/{w['eng_free']['id']}/scope", json={"pop_ids": [pa]}, headers=_as(client, w["eng_a"])).status_code == 403   # a scoped engineer cannot manage anyone
    assert client.put(f"/v1/team/members/{w['admin']['id']}/scope", json={"pop_ids": [pa]}, headers=h).status_code == 403                                # not on oneself
    other_admin = w["admin"]
    assert other_admin
    r = client.put(f"/v1/team/members/{w['eng_free']['id']}/scope", json={"pop_ids": []}, headers=h)
    assert r.status_code == 422                                                                                                                         # empty = use DELETE
    assert client.put(f"/v1/team/members/{w['eng_free']['id']}/scope", json={"pop_ids": [str(uuid4())]}, headers=h).status_code == 404                  # no such site here
    assert client.put(f"/v1/team/members/{w['eng_free']['id']}/scope", json={"olt_ids": [str(w['olt']['A1'])], "pop_ids": [pa]}, headers=h).status_code == 200
    assert client.put(f"/v1/team/members/{uuid4()}/scope", json={"pop_ids": [pa]}, headers=h).status_code == 404


def test_a_role_that_cannot_carry_a_scope_is_refused_and_a_role_change_cannot_smuggle_one(client, world, make):
    w, h = world, world["h_admin"]
    auditor = make(role="auditor", tenant_id=w["t"])
    assert client.put(f"/v1/team/members/{auditor['id']}/scope", json={"pop_ids": [str(w['pop']['A'])]}, headers=h).status_code == 409
    r = client.put(f"/v1/members/{w['eng_a']['id']}/role", json={"role": "auditor", "reason": "Mudança de função"}, headers=h)
    assert r.status_code == 409 and r.json() == {"detail": "clear_scope_first"}
    assert client.delete(f"/v1/team/members/{w['eng_a']['id']}/scope", headers=h).status_code == 200
    assert client.put(f"/v1/members/{w['eng_a']['id']}/role", json={"role": "auditor", "reason": "Mudança de função"}, headers=h).status_code == 200


def test_assigning_is_audited_and_the_team_list_shows_who_is_restricted(client, world, migrated):
    w, h = world, world["h_admin"]
    rows = {m["user_id"]: m for m in client.get("/v1/team", headers=h).json()["members"]}
    assert rows[str(w["eng_a"]["id"])]["scope"] == {"restricted": True, "pops": 1, "olts": 0} and rows[str(w["eng_a"]["id"])]["can_scope"] is True
    assert rows[str(w["eng_free"]["id"])]["scope"]["restricted"] is False and rows[str(w["admin"]["id"])]["can_scope"] is False
    with migrated.connect() as c:
        a = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE tenant_id = :t AND action = 'member.scope.set' ORDER BY created_at"), {"t": w["t"]}).all()
    assert len(a) == 4 and str(w["pop"]["A"]) in str(a[0][0]["pops"])
    g = client.get(f"/v1/team/members/{w['eng_a']['id']}/scope", headers=h).json()
    assert g["restricted"] is True and g["pop_ids"] == [str(w["pop"]["A"])] and {o["name"] for o in g["options"]["olts"]} >= {"OLT-A1-OK", "OLT-B1-SECRETA"}


# ============================================================ what a scoped person sees
def test_lists_totals_and_details_show_only_the_scope_and_what_is_outside_does_not_exist(client, world):
    w = world
    h = _as(client, w["eng_a"])
    olts = client.get("/v1/olts", headers=h)
    assert olts.status_code == 200
    body = olts.text
    assert "OLT-A1-OK" in body and "OLT-A2-OK" in body and "OLT-B1" not in body
    onus = client.get("/v1/onus", headers=h)
    assert onus.status_code == 200 and "SERA1" in onus.text and "SERB1" not in onus.text
    assert client.get(f"/v1/onus/{w['onu']['B1-1']}", headers=h).status_code == 404                                  # outside: as if it did not exist
    assert client.get(f"/v1/onus/{w['onu']['A1-1']}", headers=h).status_code == 200
    assert client.get(f"/v1/olts/{w['olt']['B1']}/queries", headers=h).status_code in (404, 200) and "OLT-B1" not in client.get(f"/v1/olts/{w['olt']['B1']}/queries", headers=h).text
    inc = client.get("/v1/incidents", headers=h)
    assert inc.status_code == 200 and "dk-B1" not in inc.text and str(w["inc"]["B1"]) not in inc.text
    assert client.get(f"/v1/incidents/{w['inc']['B1']}", headers=h).status_code == 404
    pops = client.get("/v1/pops", headers=h).text
    assert "SITE-A-OK" in pops and "SITE-B" not in pops and "SITE-C" not in pops                                     # sites without a visible OLT are hidden too
    cpes = client.get("/v1/cpes", headers=h).text
    assert "CPEAOK" in cpes and "CPEBSECRETA" not in cpes and "CPEXOK" not in cpes                                   # a CPE is visible only through a visible ONU
    assert client.get(f"/v1/cpes/{w['cpe']['B']}", headers=h).status_code == 404 and client.get(f"/v1/cpes/{w['cpe']['X']}", headers=h).status_code == 404
    hist = client.get(f"/v1/onus/{w['onu']['B1-1']}/history", headers=h)
    assert hist.status_code in (404, 200) and "EVB1" not in hist.text
    free = _as(client, w["eng_free"])
    assert "OLT-B1-SECRETA" in client.get("/v1/olts", headers=free).text and "SERB1" in client.get("/v1/onus", headers=free).text   # an unscoped colleague sees everything: nothing changed for them
    assert "OLT-B1-SECRETA" in client.get("/v1/olts", headers=w["h_admin"]).text


def test_a_second_scoped_person_sees_only_their_own_olt(client, world):
    h = _as(client, world["eng_b"])
    t = client.get("/v1/olts", headers=h).text + client.get("/v1/onus", headers=h).text
    assert "OLT-B1-SECRETA" in t and "OLT-A1" not in t and "SERA1" not in t


def test_an_empty_scope_sees_nothing_never_everything(client, world):
    h = _as(client, world["eng_empty"])                          # a site without OLTs: the resolved set is EMPTY, which restricts to nothing
    for url in ("/v1/olts", "/v1/onus", "/v1/incidents", "/v1/cpes", "/v1/pops", "/v1/fleet/olts"):
        r = client.get(url, headers=h)
        assert r.status_code == 200 and not SECRETS_RE.search(r.text) and "OLT-A" not in r.text and "SERA" not in r.text and "CPEAOK" not in r.text, url


def test_scope_changes_apply_on_the_next_request_without_a_new_login_and_a_site_that_gains_an_olt_widens_it(client, world, migrated):
    w = world
    h = _as(client, w["eng_a"])
    assert "OLT-B1" not in client.get("/v1/olts", headers=h).text
    assert client.put(f"/v1/team/members/{w['eng_a']['id']}/scope", json={"pop_ids": [str(w["pop"]["A"])], "olt_ids": [str(w["olt"]["B1"])]}, headers=w["h_admin"]).status_code == 200
    assert "OLT-B1-SECRETA" in client.get("/v1/olts", headers=h).text                       # same token
    with migrated.begin() as c:                                                              # a new OLT in site A is in the scope at once
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": w["t"]})
        c.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, pop_id) VALUES (:t,:e,'OLT-A3-NOVA','huawei',:p)"), {"t": w["t"], "e": w["edge"], "p": w["pop"]["A"]})
    assert "OLT-A3-NOVA" in client.get("/v1/olts", headers=h).text
    assert client.delete(f"/v1/team/members/{w['eng_a']['id']}/scope", headers=w["h_admin"]).json() == {"restricted": False, "cleared": True}
    assert "OLT-B1-SECRETA" in client.get("/v1/olts", headers=h).text                       # whole provider again
    assert client.delete(f"/v1/team/members/{w['eng_a']['id']}/scope", headers=w["h_admin"]).json() == {"restricted": False, "cleared": False}


def test_a_scoped_person_loses_every_permission_that_is_not_network_data_or_is_not_a_read(client, world):
    w = world
    h = _as(client, w["eng_a"])
    me = client.get("/v1/auth/me", headers=h).json()
    assert me["scope"] == {"restricted": True, "olts": 2} and {p["name"] for p in me["permissions"]} == {"tenant:read", "inventory:read", "incidents:read", "fleet:read", "discovery:read"} & {p["name"] for p in me["permissions"]} | set()
    assert {p["name"] for p in me["permissions"]} <= scope_mod.SCOPED_ALLOWED_PERMISSIONS
    assert client.get("/v1/members", headers=h).status_code == 403 and client.get("/v1/audit", headers=h).status_code == 403
    assert client.get("/v1/customers", headers=h).status_code in (403, 404)
    assert client.post("/v1/fleet/olts", json={"name": "NOVA-X", "edge_id": str(w["edge"]), "vendor": "huawei"}, headers=h).status_code == 403
    free = client.get("/v1/auth/me", headers=_as(client, w["eng_free"])).json()
    assert free["scope"] == {"restricted": False, "olts": None} and len(free["permissions"]) > 5          # an unscoped person keeps the whole role


def test_a_support_role_with_scope_keeps_only_the_network_read(client, world):
    h = _as(client, world["support"])
    assert client.get("/v1/customers", headers=h).status_code in (403, 404)
    assert "SERB1" not in client.get("/v1/onus", headers=h).text and "SERA1" in client.get("/v1/onus", headers=h).text


# ============================================================ the mandatory inventory (ADR-0031 item 3)
def _fill(path: str, w: dict) -> str:
    vals = {"olt_id": w["olt"]["B1"], "onu_id": w["onu"]["B1-1"], "cpe_id": w["cpe"]["B"], "incident_id": w["inc"]["B1"], "section": "x"}

    def sub(m):
        return str(vals.get(m.group(1), uuid4()))
    return re.sub(r"\{(\w+)\}", sub, path)


def test_every_read_route_a_scoped_person_can_reach_is_walked_with_out_of_scope_data_seeded_and_none_appears(client, world):
    w = world
    h = _as(client, w["eng_a"])
    rows = [r for r in inventory() if r["kind"] == "require" and set(r["permissions"]) & scope_mod.SCOPED_ALLOWED_PERMISSIONS and r["method"] == "GET"]
    assert len(rows) >= 40                                                                                               # the 42 read routes of today; a new one is walked automatically
    writes = [(r["method"], r["path"]) for r in inventory() if r["kind"] == "require" and set(r["permissions"]) & scope_mod.SCOPED_ALLOWED_PERMISSIONS and r["method"] != "GET"]
    assert not writes, f"the closed list is READ-ONLY: a route that writes must not use one of its permissions: {writes}"
    for r in rows:
        resp = client.get(_fill(r["path"], w), headers=h)
        assert resp.status_code < 500, (r["path"], resp.status_code)
        assert not SECRETS_RE.search(resp.text), (r["path"], resp.text[:300])
        for sentinel in (str(w["olt"]["B1"]), str(w["onu"]["B1-1"]), str(w["onu"]["B1-2"]), str(w["cpe"]["B"]), str(w["cpe"]["X"]), str(w["inc"]["B1"]), str(w["pop"]["B"]), str(w["pop"]["C"])):
            assert sentinel not in resp.text, (r["path"], sentinel)


def test_every_route_that_needs_a_permission_outside_the_closed_list_answers_403_to_a_scoped_person(client, world):
    w = world
    h = _as(client, w["eng_a"])
    for r in inventory():
        if r["kind"] != "require" or set(r["permissions"]) & scope_mod.SCOPED_ALLOWED_PERMISSIONS:
            continue
        if any(p.startswith(("edge:", "inventory:write", "jobs:execute")) for p in r["permissions"]):
            continue          # service-account permissions: a human role never holds them
        resp = client.request(r["method"], _fill(r["path"], w), headers=h, json={} if r["method"] != "GET" else None)
        assert resp.status_code == 403, (r["method"], r["path"], r["permissions"], resp.status_code)


# ============================================================ the table classification (a new table must be decided)
NOT_REACHABLE = {   # table -> why a scoped person cannot read it through any route they hold
    "tenants": "the provider's own row", "tenant_memberships": "members:*", "service_accounts": "edge/accounts routes need non-scopable permissions", "audit_log": "audit:read",
    "events_outbox": "no route", "processed_events": "no route", "edges": "edge:read; the OLT views show only the edge of a visible OLT", "customers": "customers:read",
    "import_batches": "customers:import", "refresh_tokens": "own session", "user_mfa": "own account", "mfa_recovery_codes": "own account", "login_attempts": "no route",
    "device_capabilities": "global catalog (vendor/model), no tenant network data", "tenant_features": "the provider's flags", "tenant_limits": "platform console", "tenant_security_policy": "policy view",
    "rbac_role_grants": "system", "rbac_protected_roles": "system", "rbac_bench_authorizers": "system", "membership_delegations": "platform:delegate", "member_invites": "members:manage",
    "member_scopes": "members:read/manage", "erp_connections": "erp:*", "erp_egress_budget": "no route", "speed_endpoints": "tenant-wide configuration (speed/health), no OLT data",
    "speed_risk_acceptances": "owner CLI", "probe_targets": "tenant-wide configuration", "profile_drafts": "profiles:* (not in the closed list)", "profile_dry_runs": "profiles:*",
    "profile_revisions": "profiles:*", "acs_connections": "acs:*", "email_queue": "no route", "api_tokens": "tokens:manage (a token itself never reaches a scoped person's routes)",
    "webhook_endpoints": "webhooks:manage", "webhook_deliveries": "webhooks:manage", "organization_closures": "platform ledger, no tenant row security, no application privilege",
    "webhook_cursor": "worker-only", "users_global": "account data; no tenant row security",
}


def test_every_table_with_row_security_is_classified_and_every_scoped_table_has_the_restrictive_policy(migrated):
    with migrated.connect() as c:
        every = {r[0] for r in c.execute(text("SELECT relname FROM pg_class WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace"))}
        rls = {r[0] for r in c.execute(text("SELECT relname FROM pg_class WHERE relkind = 'r' AND relrowsecurity AND relnamespace = 'public'::regnamespace"))}
        restrictive = {r[0] for r in c.execute(text("SELECT tablename FROM pg_policies WHERE schemaname = 'public' AND policyname = 'scope_restrict' AND permissive = 'RESTRICTIVE'"))}
    unclassified = rls - restrictive - set(NOT_REACHABLE)
    assert not unclassified, f"decide each (scope_restrict policy, or a reason in NOT_REACHABLE): {sorted(unclassified)}"
    stale = set(NOT_REACHABLE) - every
    assert not stale, f"classified but not a table any more: {sorted(stale)}"
    assert not (restrictive & set(NOT_REACHABLE)), "a table cannot be both"
    assert len(restrictive) >= 30


def test_the_restrictive_policies_cut_the_rows_for_the_application_role_itself(world, app_engine):
    w = world
    t = str(w["t"])

    def count(sql, scope):
        with app_engine.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true), set_config('app.scope', :s, true)"), {"t": t, "s": scope})
            return c.execute(text(sql)).scalar()
    for table in ("olts", "pon_ports", "onus", "incidents", "incident_onus", "onu_state_events", "onu_cpe_links", "cpes", "pops"):
        total = count(f"SELECT count(*) FROM {table}", "")                            # noqa: S608 - fixed names
        assert total > 0, table
        assert count(f"SELECT count(*) FROM {table}", "{}") == 0, table              # restricted to nothing: no rows
    a1 = "{" + str(w["olt"]["A1"]) + "}"
    assert count("SELECT count(*) FROM olts", a1) == 1 and count("SELECT count(*) FROM onus", a1) == 2 and count("SELECT count(*) FROM pops", a1) == 1
    assert count("SELECT count(*) FROM cpes", a1) == 1 and count("SELECT count(*) FROM incidents", a1) == 1


def test_a_malformed_scope_setting_fails_closed(world, app_engine):
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError), app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true), set_config('app.scope', 'not-a-uuid-list', true)"), {"t": str(world["t"])})
        c.execute(text("SELECT count(*) FROM olts")).scalar()


def test_a_removed_olt_never_turns_a_scoped_person_into_a_free_one(client, world, migrated):
    w = world
    h = _as(client, w["eng_b"])                                    # scoped to the OLT B1 only
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": w["t"]})
        c.execute(text("DELETE FROM incident_onus WHERE incident_id = :i"), {"i": w["inc"]["B1"]})
        c.execute(text("DELETE FROM incidents WHERE olt_id = :o"), {"o": w["olt"]["B1"]})
        c.execute(text("DELETE FROM onu_state_events WHERE olt_id = :o"), {"o": w["olt"]["B1"]})
        c.execute(text("DELETE FROM onu_cpe_links WHERE onu_id IN (SELECT id FROM onus WHERE olt_id = :o)"), {"o": w["olt"]["B1"]})
        c.execute(text("DELETE FROM onus WHERE olt_id = :o"), {"o": w["olt"]["B1"]})
        c.execute(text("DELETE FROM pon_ports WHERE olt_id = :o"), {"o": w["olt"]["B1"]})
        c.execute(text("DELETE FROM olts WHERE id = :o"), {"o": w["olt"]["B1"]})
    r = client.get("/v1/olts", headers=h)
    assert r.status_code == 200 and "OLT-A1" not in r.text and "OLT-A2" not in r.text         # the row remains (restricted), the set is empty: nothing, not everything
