"""Cadastro de ACS por organização (ADR-0046 D2, migração 0052).

What is proved here: the registry of kinds and the per-kind `settings` validation (pure); the database (constraints, nobody but `app_acs_edge_report` writes what the Edge reports, the identity is immutable, one active ACS per Edge,
the CPE can only point at an ACS of its own Edge); the person's API (permissions, the flag, register/rename/activate with no loss of state, one active per Edge, bad kinds and settings with no echo); the Edge's report
(only the ACS of ITS OWN Edge and registered kind: every other case is the SAME 404 and creates nothing); the stamp on the CPEs the ingestion writes; two organizations (RLS) end to end."""
from __future__ import annotations

import json
import logging
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.api import deps
from app.core import acs
from app.core.rbac_matrix import _routes
from tests.conftest import _now, agent, hdr

SECRETS = ("hunter2-SECRET", "https://genie.example.internal:7557", "admin:pass")   # things a person might paste where they must not: none may ever come back or reach a log/audit line


def _sqla(url):
    return create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))


def _flag(migrated, tenant, on=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'acs_registry',:v) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = :v"), {"t": tenant, "v": on})


@pytest.fixture(autouse=True)
def _clean(migrated):
    def wipe():
        with migrated.begin() as c:
            c.execute(text("DELETE FROM cpe_protocol_bindings WHERE connector_id LIKE 'acs-test-%'"))
            c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'ACSTEST%'"))
            c.execute(text("DELETE FROM acs_connections"))
            c.execute(text("DELETE FROM tenant_features WHERE feature = 'acs_registry'"))
    wipe()
    yield
    wipe()


@pytest.fixture
def on(migrated, seed):
    _flag(migrated, seed["A"])
    _flag(migrated, seed["B"])


def ha(client, seed):
    return hdr(client, "alice", seed, "A")


def hb(client, seed):
    return hdr(client, "bob", seed, "B")


def mk(client, h, edge, name="Genie-1", **kw):
    return client.post("/v1/acs", headers=h, json={"name": name, "kind": "genieacs", "edge_id": str(edge), **kw})


def report(client, ah, acs_id, *, kind="genieacs", ok=True, n=7, code=None, **extra):
    body = {"acs_id": str(acs_id), "kind": kind, "ok": ok, "device_count": n if ok else None, "error_code": code, **extra}
    return client.post("/v1/edge/acs-status", headers=ah, json=body)


def row(migrated, acs_id):
    with migrated.begin() as c:
        return c.execute(text("SELECT * FROM acs_connections WHERE id = :i"), {"i": acs_id}).one()


def cpe_snap(inv, key, serials, observed=None):
    return {"edge_id": str(inv[key]["edge"]), "observed_at": observed or _now(), "cpes": [
        {"canonical_serial": s, "vendor": "Huawei", "model": "HG8245H", "binding": {"protocol": "tr069", "external_id": f"ext-{s}", "connector_id": f"acs-test-{key}"}} for s in serials]}


def cpe_acs(migrated, serial):
    with migrated.begin() as c:
        return c.execute(text("SELECT acs_id FROM cpes WHERE canonical_serial = :s"), {"s": serial}).scalar_one()


# ------------------------------------------------------------------ the registry (pure)
def test_the_registry_and_its_validators_agree_and_the_only_kind_is_genieacs():
    assert acs.ACS_KINDS == ("genieacs",)
    assert set(acs.ACS_KINDS) == set(acs.SETTINGS_VALIDATORS)
    assert set(acs.ACS_ERROR_LABELS) == set(acs.ACS_ERROR_CODES)
    assert all(v.strip() for v in acs.ACS_ERROR_LABELS.values())


def test_settings_of_genieacs_accept_only_the_scheme_and_never_echo_what_was_sent():
    assert acs.validate_settings("genieacs", None) == {} and acs.validate_settings("genieacs", {}) == {}
    assert acs.validate_settings("genieacs", {"nbi_scheme": "https"}) == {"nbi_scheme": "https"}
    for bad, code in (({"nbi_scheme": "ftp"}, "settings_bad_value"), ({"nbi_scheme": ["http"]}, "settings_bad_value"), ({"nbi_url": SECRETS[1]}, "settings_unknown_key"),
                      ({"password": SECRETS[0]}, "settings_unknown_key"), ({"host": "10.0.0.5"}, "settings_unknown_key"), ({SECRETS[2]: 1}, "settings_unknown_key"),
                      ({"nbi_scheme": "http", "extra": 1}, "settings_unknown_key"), ("not-a-dict", "settings_bad_value"), ({"nbi_scheme": "x" * 4000}, "settings_too_large")):
        with pytest.raises(acs.SettingsError) as exc:
            acs.validate_settings("genieacs", bad)
        assert exc.value.code == code
        assert not any(s in str(exc.value) for s in SECRETS)
    with pytest.raises(acs.SettingsError):
        acs.validate_settings("other", {})


def test_adding_a_kind_is_a_change_of_the_registry_only(monkeypatch):
    """No migration: the database only checks the SHAPE of `kind`, and a new kind passes the whole API once it is in the registry."""
    monkeypatch.setattr(acs, "ACS_KINDS", ("genieacs", "acme_acs"))
    monkeypatch.setitem(acs.SETTINGS_VALIDATORS, "acme_acs", lambda s: {} if not s else (_ for _ in ()).throw(acs.SettingsError("settings_unknown_key")))
    acs.check_registry()
    assert acs.validate_settings("acme_acs", {}) == {}


# ------------------------------------------------------------------ the database
def test_the_database_constrains_the_row_and_the_application_role_cannot_write_what_the_edge_reports(on, client, seed, inv, migrated, app_url):
    r = mk(client, ha(client, seed), inv["a1"]["edge"])
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    eng = _sqla(app_url)

    def run(sql, args=None, tenant=None):
        with eng.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant or seed["A"])})
            res = conn.execute(text(sql), args or {})
            return res.all() if res.returns_rows else res.rowcount
    try:
        for sql in ("UPDATE acs_connections SET last_seen_at = now() WHERE id = :i", "UPDATE acs_connections SET last_ok_at = now() WHERE id = :i", "UPDATE acs_connections SET device_count = 5 WHERE id = :i",
                    "UPDATE acs_connections SET last_error_code = 'timeout' WHERE id = :i", "UPDATE acs_connections SET kind = 'other' WHERE id = :i", "UPDATE acs_connections SET edge_id = edge_id WHERE id = :i",
                    "UPDATE acs_connections SET id = gen_random_uuid() WHERE id = :i", "UPDATE acs_connections SET tenant_id = tenant_id WHERE id = :i", "UPDATE acs_connections SET created_at = now() WHERE id = :i",
                    "DELETE FROM acs_connections WHERE id = :i"):
            with pytest.raises(DBAPIError) as exc:
                run(sql, {"i": aid})
            assert "permission denied" in str(exc.value), sql
        with pytest.raises(DBAPIError) as exc:   # not even at creation: the state columns have no INSERT grant either
            run("INSERT INTO acs_connections (tenant_id, name, kind, edge_id, device_count) VALUES (:t, 'Sneaky', 'genieacs', :e, 99)", {"t": seed["A"], "e": inv["a1"]["edge"]})
        assert "permission denied" in str(exc.value)
        with pytest.raises(DBAPIError) as exc:
            run("INSERT INTO acs_connections (tenant_id, name, kind, edge_id, last_ok_at) VALUES (:t, 'Sneaky2', 'genieacs', :e, now())", {"t": seed["A"], "e": inv["a1"]["edge"]})
        assert "permission denied" in str(exc.value)
        # what a person MAY edit goes through, and the CHECKs hold
        assert run("UPDATE acs_connections SET name = 'Renamed', label = 'x', enabled = false, settings = '{}'::jsonb, updated_at = now() WHERE id = :i", {"i": aid}) == 1
        for sql in ("UPDATE acs_connections SET name = 'x'", "UPDATE acs_connections SET name = ' padded '", "UPDATE acs_connections SET label = ''", "UPDATE acs_connections SET settings = '[]'::jsonb",
                    "UPDATE acs_connections SET settings = jsonb_build_object('k', repeat('x', 3000))"):
            with pytest.raises(DBAPIError) as exc:
                run(sql + " WHERE id = :i", {"i": aid})
            assert "violates check constraint" in str(exc.value), sql
    finally:
        eng.dispose()
    # the OWNER cannot change the identity either (the guard is a trigger, not a grant), and the Edge-reported columns have shape CHECKs
    for sql in ("UPDATE acs_connections SET kind = 'other'", "UPDATE acs_connections SET edge_id = :e2", "UPDATE acs_connections SET id = gen_random_uuid()", "UPDATE acs_connections SET created_at = now()"):
        with pytest.raises(DBAPIError) as exc, migrated.begin() as c:
            c.execute(text(sql + " WHERE id = :i"), {"i": aid, "e2": inv["a2"]["edge"]})
        assert "immutable" in str(exc.value), sql
    for sql in ("UPDATE acs_connections SET device_count = -1", "UPDATE acs_connections SET last_error_code = 'Not A Code'", "UPDATE acs_connections SET last_ok_at = now()"):   # the last: ok without ever being seen
        with pytest.raises(DBAPIError) as exc, migrated.begin() as c:
            c.execute(text(sql + " WHERE id = :i"), {"i": aid})
        assert "violates check constraint" in str(exc.value), sql
    with pytest.raises(DBAPIError) as exc, migrated.begin() as c:   # a kind the registry may not have yet is fine for the database, a malformed one is not
        c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id) VALUES (:t, 'Bad Kind', 'Gene ACS', :e)"), {"t": seed["A"], "e": inv["a2"]["edge"]})
    assert "violates check constraint" in str(exc.value)
    with migrated.begin() as c:
        c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id, enabled) VALUES (:t, 'New Kind', 'acme_acs', :e, false)"), {"t": seed["A"], "e": inv["a2"]["edge"]})


def test_the_database_allows_one_active_acs_per_edge_and_only_edges_of_the_same_tenant(on, seed, inv, migrated):
    with migrated.begin() as c:
        c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id) VALUES (:t, 'One', 'genieacs', :e)"), {"t": seed["A"], "e": inv["a1"]["edge"]})
    with pytest.raises(DBAPIError) as exc, migrated.begin() as c:   # second ACTIVE on the same Edge
        c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id) VALUES (:t, 'Two', 'genieacs', :e)"), {"t": seed["A"], "e": inv["a1"]["edge"]})
    assert "acs_connections_one_active_per_edge" in str(exc.value)
    with migrated.begin() as c:   # inactive ones are unlimited; another Edge is its own slot
        c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id, enabled) VALUES (:t, 'Two', 'genieacs', :e, false), (:t, 'Three', 'genieacs', :e, false)"), {"t": seed["A"], "e": inv["a1"]["edge"]})
        c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id) VALUES (:t, 'One', 'genieacs', :e)"), {"t": seed["A"], "e": inv["a2"]["edge"]})   # same name, other Edge: fine
    with pytest.raises(DBAPIError) as exc, migrated.begin() as c:   # the name is unique per Edge without regard to case
        c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id, enabled) VALUES (:t, 'ONE', 'genieacs', :e, false)"), {"t": seed["A"], "e": inv["a1"]["edge"]})
    assert "acs_connections_name_ci" in str(exc.value)
    with pytest.raises(DBAPIError) as exc, migrated.begin() as c:   # an Edge of ANOTHER tenant: the composite foreign key refuses it
        c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id) VALUES (:t, 'Cross', 'genieacs', :e)"), {"t": seed["A"], "e": inv["b1"]["edge"]})
    assert "foreign key" in str(exc.value)


def test_a_cpe_can_only_point_at_an_acs_of_its_own_edge(on, seed, inv, migrated):
    with migrated.begin() as c:
        a1 = c.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id) VALUES (:t, 'One', 'genieacs', :e) RETURNING id"), {"t": seed["A"], "e": inv["a1"]["edge"]}).scalar()
        c.execute(text("INSERT INTO cpes (tenant_id, edge_id, canonical_serial, acs_id) VALUES (:t, :e, 'ACSTEST-FK-1', :a)"), {"t": seed["A"], "e": inv["a1"]["edge"], "a": a1})
    with pytest.raises(DBAPIError) as exc, migrated.begin() as c:   # a CPE of Edge a2 pointing at the ACS of Edge a1
        c.execute(text("INSERT INTO cpes (tenant_id, edge_id, canonical_serial, acs_id) VALUES (:t, :e, 'ACSTEST-FK-2', :a)"), {"t": seed["A"], "e": inv["a2"]["edge"], "a": a1})
    assert "cpes_acs_fk" in str(exc.value)
    with pytest.raises(DBAPIError), migrated.begin() as c:   # an ACS id that does not exist
        c.execute(text("INSERT INTO cpes (tenant_id, edge_id, canonical_serial, acs_id) VALUES (:t, :e, 'ACSTEST-FK-3', gen_random_uuid())"), {"t": seed["A"], "e": inv["a1"]["edge"]})
    with pytest.raises(DBAPIError), migrated.begin() as c:   # the ACS of another tenant
        c.execute(text("INSERT INTO cpes (tenant_id, edge_id, canonical_serial, acs_id) VALUES (:t, :e, 'ACSTEST-FK-4', :a)"), {"t": seed["B"], "e": inv["b1"]["edge"], "a": a1})


def test_the_narrow_function_only_touches_the_acs_of_the_calling_edge_in_the_session_tenant(on, client, seed, inv, migrated, app_url):
    aid = mk(client, ha(client, seed), inv["a1"]["edge"]).json()["id"]
    eng = _sqla(app_url)

    def call(args, tenant=seed["A"]):
        with eng.begin() as conn:
            if tenant is not None:
                conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
            return conn.execute(text("SELECT app_acs_edge_report(:a, :e, :k, :ok, :n, :c)"), {"a": args.get("a", aid), "e": args.get("e", inv["a1"]["edge"]), "k": args.get("k", "genieacs"),
                                                                                                   "ok": args.get("ok", True), "n": args.get("n", 3), "c": args.get("c")}).scalar()
    try:
        assert call({"e": inv["a2"]["edge"]}) == "ignored"                  # another Edge of the same tenant
        assert call({"k": "other"}) == "ignored"                            # another kind
        assert call({"a": str(uuid.uuid4())}) == "ignored"                  # unknown id
        assert call({}, tenant=seed["B"]) == "ignored"                      # another tenant's session: RLS hides the row
        assert call({}, tenant=None) == "ignored"                           # no tenant in the session: nothing is visible
        assert row(migrated, aid).last_seen_at is None                      # none of the above touched it
        assert call({}) == "changed"                                        # first report
        assert call({}) == "same"
        assert call({"ok": False, "n": None, "c": "timeout"}) == "changed"
        assert call({"ok": False, "n": None, "c": "timeout"}) == "same"
        for bad in ({"ok": True, "c": "timeout"}, {"ok": True, "n": None}, {"ok": False, "n": 1, "c": "timeout"}, {"ok": False, "n": None, "c": None}):
            with pytest.raises(DBAPIError):
                call(bad)
    finally:
        eng.dispose()
    r = row(migrated, aid)
    assert (r.device_count, r.last_error_code) == (3, "timeout") and r.last_ok_at is not None and r.last_seen_at >= r.last_ok_at   # a failure keeps the last known count and the last OK time


# ------------------------------------------------------------------ the person's API
def test_the_flag_is_off_by_default_and_every_route_answers_403_without_touching_anything(client, seed, inv, migrated):
    h = ha(client, seed)
    for method, path, body in (("GET", "/v1/acs", None), ("POST", "/v1/acs", {"name": "Genie-1", "kind": "genieacs", "edge_id": str(inv["a1"]["edge"])}),
                               ("GET", f"/v1/acs/{uuid.uuid4()}", None), ("PATCH", f"/v1/acs/{uuid.uuid4()}", {"label": "x"})):
        r = client.request(method, path, headers=h, json=body)
        assert (r.status_code, r.json()["detail"]) == (403, "feature_disabled"), path
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM acs_connections")).scalar() == 0


def test_permissions_read_for_the_catalogued_roles_manage_only_for_the_administrator(on, client, seed, inv):
    h_admin = ha(client, seed)
    aid = mk(client, h_admin, inv["a1"]["edge"]).json()["id"]
    h_auditor = hdr(client, "carol", seed, "A")     # auditor in A
    h_noc1 = hdr(client, "dave", seed, "A")         # noc_n1 in A: no acs permission at all
    assert client.get("/v1/acs", headers=h_auditor).status_code == 200 and client.get(f"/v1/acs/{aid}", headers=h_auditor).status_code == 200
    assert client.post("/v1/acs", headers=h_auditor, json={"name": "Genie-2", "kind": "genieacs", "edge_id": str(inv["a2"]["edge"])}).status_code == 403
    assert client.patch(f"/v1/acs/{aid}", headers=h_auditor, json={"label": "x"}).status_code == 403
    for h in (h_noc1, {}):
        assert client.get("/v1/acs", headers=h).status_code in (401, 403)
        assert client.get(f"/v1/acs/{aid}", headers=h).status_code in (401, 403)
        assert client.post("/v1/acs", headers=h, json={"name": "Genie-2", "kind": "genieacs", "edge_id": str(inv["a2"]["edge"])}).status_code in (401, 403)
    assert client.get("/v1/acs", headers=h_noc1).status_code == 403
    # the Edge's service account holds neither permission: it cannot use the person's routes
    assert client.get("/v1/acs", headers=agent(client, inv, "a1")).status_code == 403
    assert client.post("/v1/acs", headers=agent(client, inv, "a1"), json={"name": "Genie-2", "kind": "genieacs", "edge_id": str(inv["a1"]["edge"])}).status_code == 403


def test_an_engineer_reads_and_cannot_manage(on, client, seed, inv):
    hbob, hc = hb(client, seed), hdr(client, "carol", seed, "B")
    aid = mk(client, hbob, inv["b1"]["edge"]).json()["id"]
    assert client.get("/v1/acs", headers=hc).status_code == 200 and client.get(f"/v1/acs/{aid}", headers=hc).status_code == 200
    assert client.post("/v1/acs", headers=hc, json={"name": "Genie-2", "kind": "genieacs", "edge_id": str(inv["b1"]["edge"]), "enabled": False}).status_code == 403
    assert client.patch(f"/v1/acs/{aid}", headers=hc, json={"enabled": False}).status_code == 403


def test_register_read_list_and_the_exact_shape(on, client, seed, inv):
    h = ha(client, seed)
    r = mk(client, h, inv["a1"]["edge"], label="Matriz", settings={"nbi_scheme": "https"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert set(v) == {"id", "name", "kind", "label", "enabled", "settings", "edge", "created_at", "updated_at", "last_seen_at", "last_ok_at", "device_count", "last_error_code", "health"}
    assert (v["name"], v["kind"], v["label"], v["enabled"], v["settings"], v["health"]) == ("Genie-1", "genieacs", "Matriz", True, {"nbi_scheme": "https"}, "unknown")
    assert v["edge"] == {"id": str(inv["a1"]["edge"]), "name": "inv-a1"} and v["device_count"] is None and v["last_seen_at"] is None
    assert client.get(f"/v1/acs/{v['id']}", headers=h).json() == v
    lst = client.get("/v1/acs", headers=h).json()
    assert lst["items"] == [v] and lst["kinds"] == ["genieacs"] and lst["truncated"] is False
    assert client.get(f"/v1/acs/{uuid.uuid4()}", headers=h).status_code == 404
    assert client.get("/v1/acs/not-a-uuid", headers=h).status_code == 422


def test_register_refuses_bad_input_and_never_echoes_what_was_sent(on, client, seed, inv, caplog):
    caplog.set_level(logging.DEBUG)
    h = ha(client, seed)
    e = str(inv["a1"]["edge"])
    cases = [
        ({"name": "Genie-1", "kind": "zabbix", "edge_id": e}, 422),                                         # unknown kind
        ({"name": "Genie-1", "kind": "genieacs", "edge_id": e, "settings": {"nbi_url": SECRETS[1]}}, 422),
        ({"name": "Genie-1", "kind": "genieacs", "edge_id": e, "settings": {"password": SECRETS[0]}}, 422),
        ({"name": "Genie-1", "kind": "genieacs", "edge_id": e, "settings": {"nbi_scheme": SECRETS[2]}}, 422),
        ({"name": "Genie-1", "kind": "genieacs", "edge_id": e, "settings": {"nbi_scheme": "x" * 5000}}, 422),
        ({"name": "Genie-1", "kind": "genieacs", "edge_id": e, "password": SECRETS[0]}, 422),               # an unknown field
        ({"name": "x", "kind": "genieacs", "edge_id": e}, 422), ({"name": "x" * 61, "kind": "genieacs", "edge_id": e}, 422),
        ({"name": "Genie-1", "kind": "genieacs", "edge_id": "nope"}, 422), ({"name": "Genie-1", "kind": "genieacs"}, 422),
        ({"name": "Genie-1", "kind": "genieacs", "edge_id": e, "enabled": "yes"}, 422), ({"name": "Genie-1", "kind": "genieacs", "edge_id": e, "label": ""}, 422),
    ]
    seen = []
    for body, code in cases:
        r = client.post("/v1/acs", headers=h, json=body)
        assert r.status_code == code, (body, r.text)
        seen.append(r.text)
    assert client.get("/v1/acs", headers=h).json()["items"] == []   # nothing was created by any of them
    assert not any(s in "".join(seen) + caplog.text for s in SECRETS)
    assert client.post("/v1/acs", headers=h, json={"name": "Genie-1", "kind": "genieacs", "edge_id": e, "settings": {"nbi_url": "u"}}).json()["detail"] == "settings_unknown_key"


def test_one_active_acs_per_edge_409_and_deactivating_frees_the_slot(on, client, seed, inv):
    h = ha(client, seed)
    e1, e2 = inv["a1"]["edge"], inv["a2"]["edge"]
    first = mk(client, h, e1, "Genie-1")
    assert first.status_code == 201
    r = mk(client, h, e1, "Genie-2")                                                   # a second ACTIVE one on the same Edge
    assert (r.status_code, r.json()["detail"]) == (409, "edge_already_has_active_acs")
    second = mk(client, h, e1, "Genie-2", enabled=False)                               # an inactive one is fine
    assert second.status_code == 201 and second.json()["enabled"] is False
    r = client.patch(f"/v1/acs/{second.json()['id']}", headers=h, json={"enabled": True})   # activating it while the first is active
    assert (r.status_code, r.json()["detail"]) == (409, "edge_already_has_active_acs")
    assert mk(client, h, e2, "Genie-1").status_code == 201                              # the other Edge has its own slot (and the same name is fine there)
    assert client.patch(f"/v1/acs/{first.json()['id']}", headers=h, json={"enabled": False}).json()["enabled"] is False
    r = client.patch(f"/v1/acs/{second.json()['id']}", headers=h, json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True                         # the slot was free
    r = client.patch(f"/v1/acs/{first.json()['id']}", headers=h, json={"enabled": True})
    assert r.status_code == 409                                                         # and now it is taken again
    assert client.patch(f"/v1/acs/{second.json()['id']}", headers=h, json={"enabled": True}).status_code == 200   # re-sending the state it already has is not a conflict


def test_rename_keeps_the_identity_and_everything_the_edge_reported(on, client, seed, inv, migrated):
    h, ah = ha(client, seed), agent(client, inv, "a1")
    aid = mk(client, h, inv["a1"]["edge"]).json()["id"]
    assert report(client, ah, aid, n=42).status_code == 204
    before = row(migrated, aid)
    r = client.patch(f"/v1/acs/{aid}", headers=h, json={"name": "  Genie Matriz  ", "label": "Prédio 2", "settings": {"nbi_scheme": "http"}})
    assert r.status_code == 200
    v = r.json()
    assert (v["id"], v["name"], v["label"], v["settings"]) == (aid, "Genie Matriz", "Prédio 2", {"nbi_scheme": "http"})
    assert (v["device_count"], v["health"]) == (42, "ok") and v["last_ok_at"] == before.last_ok_at.isoformat() and v["last_seen_at"] == before.last_seen_at.isoformat()
    assert v["created_at"] == before.created_at.isoformat() and v["updated_at"] >= v["created_at"]
    assert report(client, ah, aid, n=43).status_code == 204 and client.get(f"/v1/acs/{aid}", headers=h).json()["device_count"] == 43   # the Edge keeps reporting under the same id
    # the name is a label, unique per Edge without regard to case; renaming to its own name is fine
    other = mk(client, h, inv["a1"]["edge"], "Outro", enabled=False).json()["id"]
    assert client.patch(f"/v1/acs/{other}", headers=h, json={"name": "genie matriz"}).json() == {"detail": "acs_name_taken"}
    assert client.patch(f"/v1/acs/{aid}", headers=h, json={"name": "GENIE MATRIZ"}).status_code == 200


def test_patch_cannot_change_the_kind_or_the_edge_nor_clear_what_is_required(on, client, seed, inv):
    h = ha(client, seed)
    aid = mk(client, h, inv["a1"]["edge"]).json()["id"]
    for body in ({"kind": "genieacs"}, {"edge_id": str(inv["a2"]["edge"])}, {"id": str(uuid.uuid4())}, {"tenant_id": str(uuid.uuid4())}, {"last_ok_at": _now()}, {"device_count": 5}, {"last_error_code": "timeout"},
                 {}, {"name": None}, {"enabled": None}, {"settings": None}, {"enabled": "no"}, {"settings": {"nbi_url": "http://x"}}, {"settings": {"nbi_scheme": "gopher"}}, {"name": "x"}):
        assert client.patch(f"/v1/acs/{aid}", headers=h, json=body).status_code == 422, body
    v = client.get(f"/v1/acs/{aid}", headers=h).json()
    assert (v["kind"], v["edge"]["id"], v["device_count"], v["settings"]) == ("genieacs", str(inv["a1"]["edge"]), None, {})
    assert client.patch(f"/v1/acs/{aid}", headers=h, json={"label": None}).status_code == 200   # a label may be cleared (it is optional)
    assert client.patch(f"/v1/acs/{uuid.uuid4()}", headers=h, json={"label": "x"}).status_code == 404


def test_audit_lines_carry_no_settings_value_and_the_status_line_is_written_only_when_the_state_changes(on, client, seed, inv, migrated, caplog):
    caplog.set_level(logging.DEBUG)
    h, ah = ha(client, seed), agent(client, inv, "a1")
    aid = mk(client, h, inv["a1"]["edge"], settings={"nbi_scheme": "https"}, label="Matriz").json()["id"]
    client.patch(f"/v1/acs/{aid}", headers=h, json={"settings": {"nbi_scheme": "http"}, "name": "Genie Z"})
    for _ in range(3):
        assert report(client, ah, aid).status_code == 204                     # the Edge repeats the same state every round
    assert report(client, ah, aid, ok=False, code="timeout").status_code == 204
    assert report(client, ah, aid, ok=False, code="timeout").status_code == 204
    with migrated.begin() as c:
        rows = c.execute(text("SELECT action, evidence_redacted FROM audit_log WHERE target_id = :i ORDER BY created_at"), {"i": aid}).all()
    assert [a for a, _ in rows] == ["acs.created", "acs.updated", "acs.status.changed", "acs.status.changed"]   # first report + the change to timeout; the repeats leave nothing
    blob = json.dumps([e for _, e in rows])
    assert "http" not in blob and "Matriz" not in blob                                                       # no settings value, no label
    assert rows[1][1]["fields"] == ["name", "settings"] and rows[3][1] == {"kind": "genieacs", "ok": False, "error_code": "timeout"}


# ------------------------------------------------------------------ the Edge's report
def test_the_edge_report_records_ok_and_failure_and_the_health_follows(on, client, seed, inv, migrated):
    h, ah = ha(client, seed), agent(client, inv, "a1")
    aid = mk(client, h, inv["a1"]["edge"]).json()["id"]
    assert report(client, ah, aid, n=12).status_code == 204
    v = client.get(f"/v1/acs/{aid}", headers=h).json()
    assert (v["health"], v["device_count"], v["last_error_code"]) == ("ok", 12, None) and v["last_ok_at"] and v["last_seen_at"]
    assert report(client, ah, aid, ok=False, code="unauthorized").status_code == 204
    v2 = client.get(f"/v1/acs/{aid}", headers=h).json()
    assert (v2["health"], v2["device_count"], v2["last_error_code"], v2["last_ok_at"]) == ("error", 12, "unauthorized", v["last_ok_at"])   # the last good count and time are kept
    assert report(client, ah, aid, n=0).status_code == 204 and client.get(f"/v1/acs/{aid}", headers=h).json()["last_error_code"] is None   # it recovers; zero devices is a valid answer
    with migrated.begin() as c:   # silence turns into "stale", never into a fabricated "ok"
        c.execute(text("UPDATE acs_connections SET last_seen_at = now() - interval '2 hours', last_ok_at = now() - interval '2 hours' WHERE id = :i"), {"i": aid})
    assert client.get(f"/v1/acs/{aid}", headers=h).json()["health"] == "stale"


def test_the_edge_report_contract_is_closed(on, client, seed, inv, migrated):
    h, ah = ha(client, seed), agent(client, inv, "a1")
    aid = mk(client, h, inv["a1"]["edge"]).json()["id"]
    good = {"acs_id": aid, "kind": "genieacs", "ok": True, "device_count": 3, "error_code": None}
    for bad in ({**good, "extra": 1}, {**good, "url": SECRETS[1]}, {**good, "acs_id": "nope"}, {**good, "ok": "true"}, {**good, "ok": 1}, {**good, "device_count": -1}, {**good, "device_count": 10**8}, {**good, "device_count": "3"},
                {**good, "device_count": None}, {**good, "error_code": "timeout"}, {**good, "ok": False, "device_count": None, "error_code": "http_500"}, {**good, "ok": False, "device_count": None, "error_code": None},
                {**good, "ok": False, "device_count": 3, "error_code": "timeout"}, {**good, "kind": ""}, {**good, "kind": "x" * 33},
                {k: v for k, v in good.items() if k != "acs_id"}, {k: v for k, v in good.items() if k != "kind"}, {k: v for k, v in good.items() if k != "ok"}, [good], {"items": [good]}):
        r = client.post("/v1/edge/acs-status", headers=ah, json=bad)
        assert r.status_code == 422, (bad, r.text)
        assert not any(s in r.text for s in SECRETS)
    assert row(migrated, aid).last_seen_at is None
    for code in acs.ACS_ERROR_CODES:   # every code of the closed list is accepted
        assert report(client, ah, aid, ok=False, code=code).status_code == 204
    assert client.post("/v1/edge/acs-status", headers=ah, json=good).status_code == 204
    assert client.post("/v1/edge/acs-status", json=good).status_code == 401
    assert client.post("/v1/edge/acs-status", headers=h, json=good).status_code == 403   # a person is not an Edge (jobs:execute is the service account's)


def test_the_edge_route_shares_the_ingest_budget_of_the_agent():
    r = next(x for x in _routes() if x.path == "/v1/edge/acs-status")
    calls = []

    def walk(d):
        for s in d.dependencies:
            calls.append(s.call)
            walk(s)
    walk(r.dependant)
    assert deps.edge_ingest_limit in calls and any(getattr(c, "rbac_permission", None) == "jobs:execute" for c in calls)
    names = [getattr(c, "__name__", "") for c in calls]
    assert names.index("edge_ingest_limit") > max(i for i, c in enumerate(calls) if getattr(c, "rbac_permission", None) == "jobs:execute")   # after `require`: an unauthorised caller spends nothing


def test_a_report_about_an_acs_that_is_not_the_callers_is_the_same_404_and_creates_nothing(on, client, seed, inv, migrated):
    h = ha(client, seed)
    a1, a2, b1 = (agent(client, inv, k) for k in ("a1", "a2", "b1"))
    aid = mk(client, h, inv["a1"]["edge"]).json()["id"]
    bid = mk(client, hb(client, seed), inv["b1"]["edge"]).json()["id"]
    answers = []
    for who, target, kind in ((a2, aid, "genieacs"),                       # another Edge of the same organization
                              (b1, aid, "genieacs"),                       # an Edge of another organization
                              (a1, bid, "genieacs"),                       # the other organization's ACS, from a1
                              (a1, str(uuid.uuid4()), "genieacs"),         # unknown id
                              (a1, aid, "zabbix"), (a1, aid, "acme_acs")): # a kind that is not the registered one
        r = report(client, who, target, kind=kind)
        assert r.status_code == 404, (target, kind, r.text)
        answers.append((r.json(), r.headers.get("content-type")))
    assert len({json.dumps(a) for a in answers}) == 1 and answers[0][0] == {"detail": "acs not found"}   # identical, whatever the reason
    r = report(client, a2, aid, ok=False, code="timeout")
    assert (r.status_code, r.json()) == (404, {"detail": "acs not found"})
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM acs_connections")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM acs_connections WHERE last_seen_at IS NOT NULL OR device_count IS NOT NULL OR last_error_code IS NOT NULL")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'acs.status.changed' AND target_id = ANY(:t)"), {"t": [aid, bid]}).scalar() == 0
    assert report(client, a1, aid).status_code == 204 and report(client, b1, bid).status_code == 204   # the owners themselves still can


def test_with_the_flag_off_the_edge_gets_the_same_404_and_the_state_stays_put(on, client, seed, inv, migrated):
    h, ah = ha(client, seed), agent(client, inv, "a1")
    aid = mk(client, h, inv["a1"]["edge"]).json()["id"]
    assert report(client, ah, aid).status_code == 204
    _flag(migrated, seed["A"], False)
    r = report(client, ah, aid, n=99)
    assert (r.status_code, r.json()) == (404, {"detail": "acs not found"})
    assert row(migrated, aid).device_count == 7
    assert client.get("/v1/acs", headers=h).status_code == 403


# ------------------------------------------------------------------ the stamp on the CPEs
def test_the_ingestion_stamps_the_active_acs_of_the_edge_and_nothing_else(on, client, seed, inv, migrated):
    h, a1, a2 = ha(client, seed), agent(client, inv, "a1"), agent(client, inv, "a2")
    # no ACS yet: NULL ("no origin assigned")
    assert client.post("/v1/edge/cpe-snapshots", headers=a1, json=cpe_snap(inv, "a1", ["ACSTEST-0001"])).status_code == 202
    assert cpe_acs(migrated, "ACSTEST-0001") is None
    g1 = mk(client, h, inv["a1"]["edge"], "Genie-1").json()["id"]
    assert cpe_acs(migrated, "ACSTEST-0001") is None                                              # no backfill: creating the ACS does not rewrite what was read before
    assert client.post("/v1/edge/cpe-snapshots", headers=a1, json=cpe_snap(inv, "a1", ["ACSTEST-0001", "ACSTEST-0002"])).status_code == 202
    assert (cpe_acs(migrated, "ACSTEST-0001"), cpe_acs(migrated, "ACSTEST-0002")) == (uuid.UUID(g1), uuid.UUID(g1))   # the next read carries it
    # another Edge of the same organization with no ACS: its CPEs stay NULL, whatever a1 has (never inferred across Edges)
    assert client.post("/v1/edge/cpe-snapshots", headers=a2, json=cpe_snap(inv, "a2", ["ACSTEST-0003"])).status_code == 202
    assert cpe_acs(migrated, "ACSTEST-0003") is None
    # the API shows it
    by_serial = {c["canonical_serial"]: c for c in client.get("/v1/cpes", headers=h).json()}
    assert by_serial["ACSTEST-0002"]["acs_id"] == g1 and by_serial["ACSTEST-0003"]["acs_id"] is None
    assert client.get(f"/v1/cpes/{by_serial['ACSTEST-0002']['id']}", headers=h).json()["acs_id"] == g1
    # switching the active ACS: old CPEs are NOT rewritten; each new read carries the one in force
    g2 = mk(client, h, inv["a1"]["edge"], "Genie-2", enabled=False).json()["id"]
    client.patch(f"/v1/acs/{g1}", headers=h, json={"enabled": False})
    client.patch(f"/v1/acs/{g2}", headers=h, json={"enabled": True})
    assert cpe_acs(migrated, "ACSTEST-0002") == uuid.UUID(g1)
    assert client.post("/v1/edge/cpe-snapshots", headers=a1, json=cpe_snap(inv, "a1", ["ACSTEST-0002"])).status_code == 202
    assert (cpe_acs(migrated, "ACSTEST-0002"), cpe_acs(migrated, "ACSTEST-0001")) == (uuid.UUID(g2), uuid.UUID(g1))
    # no active ACS any more: the next read says "no origin"
    client.patch(f"/v1/acs/{g2}", headers=h, json={"enabled": False})
    assert client.post("/v1/edge/cpe-snapshots", headers=a1, json=cpe_snap(inv, "a1", ["ACSTEST-0002"])).status_code == 202
    assert cpe_acs(migrated, "ACSTEST-0002") is None
    # the flag off: the stamp is inert too
    client.patch(f"/v1/acs/{g1}", headers=h, json={"enabled": True})
    _flag(migrated, seed["A"], False)
    assert client.post("/v1/edge/cpe-snapshots", headers=a1, json=cpe_snap(inv, "a1", ["ACSTEST-0001"])).status_code == 202
    assert cpe_acs(migrated, "ACSTEST-0001") is None


def test_an_edge_of_another_organization_never_gets_a_stamp_from_this_ones_acs(on, client, seed, inv, migrated):
    ha_, hb_ = ha(client, seed), hb(client, seed)
    ga = mk(client, ha_, inv["a1"]["edge"]).json()["id"]
    gb = mk(client, hb_, inv["b1"]["edge"]).json()["id"]
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "b1"), json=cpe_snap(inv, "b1", ["ACSTEST-B-1"])).status_code == 202
    assert cpe_acs(migrated, "ACSTEST-B-1") == uuid.UUID(gb) != uuid.UUID(ga)
    assert client.get("/v1/cpes", headers=ha_).json() == [] or all(c["canonical_serial"] != "ACSTEST-B-1" for c in client.get("/v1/cpes", headers=ha_).json())


# ------------------------------------------------------------------ two organizations
def test_rls_an_organization_never_sees_nor_changes_nor_reports_for_the_acs_of_another(on, client, seed, inv, migrated, app_url):
    ha_, hb_ = ha(client, seed), hb(client, seed)
    ga = mk(client, ha_, inv["a1"]["edge"], "Genie-A", label="só da A").json()["id"]
    gb = mk(client, hb_, inv["b1"]["edge"], "Genie-A").json()["id"]               # the same NAME in another organization is its own thing
    assert report(client, agent(client, inv, "a1"), ga, n=5).status_code == 204
    # B sees only its own
    assert [x["id"] for x in client.get("/v1/acs", headers=hb_).json()["items"]] == [gb]
    assert ga not in client.get("/v1/acs", headers=hb_).text and "só da A" not in client.get("/v1/acs", headers=hb_).text
    assert client.get(f"/v1/acs/{ga}", headers=hb_).status_code == 404
    assert client.patch(f"/v1/acs/{ga}", headers=hb_, json={"enabled": False, "name": "Hijack"}).status_code == 404
    # B cannot register an ACS on A's Edge (404, the same as a missing Edge), nor A on B's
    for h, edge in ((hb_, inv["a1"]["edge"]), (ha_, inv["b1"]["edge"]), (ha_, uuid.uuid4())):
        r = client.post("/v1/acs", headers=h, json={"name": "Cross", "kind": "genieacs", "edge_id": str(edge), "enabled": False})
        assert (r.status_code, r.json()) == (404, {"detail": "edge not found"})
    # B's Edge cannot report for A's ACS (the 404 test above) and A's untouched
    assert report(client, agent(client, inv, "b1"), ga, n=999).status_code == 404
    v = client.get(f"/v1/acs/{ga}", headers=ha_).json()
    assert (v["name"], v["enabled"], v["device_count"], v["label"]) == ("Genie-A", True, 5, "só da A")
    eng = _sqla(app_url)
    try:
        with eng.begin() as conn:   # under B's session the database itself shows nothing of A's row and changes nothing
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
            assert conn.execute(text("SELECT count(*) FROM acs_connections WHERE id = :i"), {"i": ga}).scalar() == 0
            assert conn.execute(text("UPDATE acs_connections SET name = 'Hijack' WHERE id = :i"), {"i": ga}).rowcount == 0
            assert conn.execute(text("SELECT app_acs_edge_report(:a, :e, 'genieacs', true, 1, NULL)"), {"a": ga, "e": inv["a1"]["edge"]}).scalar() == "ignored"
            with pytest.raises(DBAPIError):   # and cannot even INSERT a row for A's tenant
                conn.execute(text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id) VALUES (:t, 'Forged', 'genieacs', :e)"), {"t": seed["A"], "e": inv["a2"]["edge"]})
    finally:
        eng.dispose()
    # the audit trail of A is not in B's
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE target_id = :i AND tenant_id = :t"), {"i": ga, "t": seed["B"]}).scalar() == 0
