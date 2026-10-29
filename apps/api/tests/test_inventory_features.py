"""Per-tenant feature flags (ADR-0023): code defaults, per-tenant override, kill switch, owner-only writes, isolation."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import features
from tests.conftest import _now, agent, hdr, login, snap


@pytest.fixture(autouse=True)
def _reset_flags(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features"))
        c.execute(text("DELETE FROM cpe_protocol_bindings WHERE cpe_id IN (SELECT id FROM cpes WHERE canonical_serial LIKE 'FLAG-%')"))
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'FLAG-%'"))
        c.execute(text("DELETE FROM onus WHERE serial LIKE 'FLAG-%'"))
        c.execute(text("DELETE FROM pon_ports WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-FLAG-%')"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-FLAG-%'"))


def _flag(migrated, tenant, feature, on):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,:e)"), {"t": tenant, "f": feature, "e": on})


def _as_map(client, h):
    r = client.get("/v1/tenant/features", headers=h)
    assert r.status_code == 200, r.text
    return {x["feature"]: x for x in r.json()}


def test_defaults_come_from_code_shipped_on_new_off(client, seed):
    m = _as_map(client, hdr(client, "alice", seed, "A"))
    assert set(m) == set(features.FEATURES)
    assert m["capability_registry"] == {"feature": "capability_registry", "enabled": True, "source": "default"}
    assert all(not m[f]["enabled"] and m[f]["source"] == "default" for f in ("onu_cpe_links", "customer_context", "subscriber_360"))


def test_override_is_per_tenant_and_reported_as_such(client, seed, migrated):
    _flag(migrated, seed["A"], "subscriber_360", True)
    a, b = _as_map(client, hdr(client, "alice", seed, "A")), _as_map(client, hdr(client, "bob", seed, "B"))
    assert a["subscriber_360"] == {"feature": "subscriber_360", "enabled": True, "source": "tenant"}
    assert b["subscriber_360"]["enabled"] is False and b["subscriber_360"]["source"] == "default"  # tenant B is untouched


def test_kill_switch_turns_a_shipped_capability_off_for_one_tenant_only(client, seed, inv, migrated):
    for name, key in (("OLT-FLAG-A", "a1"), ("OLT-FLAG-B", "b1")):
        body = snap(inv, key, name=name, onus=[{"serial": f"FLAG-{name}", "pon_path": "0/1/0", "status": "online"}])
        assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, key), json=body).status_code == 202
    ha, hb = hdr(client, "alice", seed, "A"), hdr(client, "bob", seed, "B")
    oa = next(o["id"] for o in client.get("/v1/olts", headers=ha).json() if o["name"] == "OLT-FLAG-A")
    ob = next(o["id"] for o in client.get("/v1/olts", headers=hb).json() if o["name"] == "OLT-FLAG-B")
    assert client.get(f"/v1/olts/{oa}/capabilities", headers=ha).status_code == 200
    _flag(migrated, seed["A"], "capability_registry", False)
    off = client.get(f"/v1/olts/{oa}/capabilities", headers=ha)
    assert off.status_code == 403 and off.json()["detail"] == "feature_disabled"
    assert client.get(f"/v1/olts/{ob}/capabilities", headers=hb).status_code == 200  # B keeps it


def test_kill_switch_also_covers_the_cpe_route(client, seed, inv, migrated):
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": "FLAG-CPE-0001", "vendor": "V", "model": "M", "firmware": "1",
         "binding": {"protocol": "tr069", "external_id": "flag-cpe-ext", "connector_id": "c-flag"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    ha = hdr(client, "alice", seed, "A")
    cid = next(c["id"] for c in client.get("/v1/cpes", headers=ha).json() if c["canonical_serial"] == "FLAG-CPE-0001")
    assert client.get(f"/v1/cpes/{cid}/capabilities", headers=ha).status_code == 200
    _flag(migrated, seed["A"], "capability_registry", False)
    r = client.get(f"/v1/cpes/{cid}/capabilities", headers=ha)
    assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"


def test_listing_needs_tenant_read_and_unknown_names_are_never_on(client, seed, inv, migrated):
    assert client.get("/v1/tenant/features").status_code == 401
    assert client.get("/v1/tenant/features", headers=agent(client, inv, "a1")).status_code == 403
    assert client.get("/v1/tenant/features", headers={**login(client, "carol"), "X-Workspace-ID": str(seed["A"])}).status_code == 200  # auditor
    with migrated.begin() as c:
        assert features.enabled(c, seed["A"], "made_up_feature") is False


def test_database_rules_and_runtime_role_is_read_only(client, seed, migrated):
    with pytest.raises(DBAPIError):
        _flag(migrated, seed["A"], "Not-A-Valid-Name!", True)
    from app.core.db import get_engine, scoped_connection
    with pytest.raises(DBAPIError), scoped_connection(get_engine(), tenant_id=seed["A"]) as c:
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'subscriber_360',true)"), {"t": seed["A"]})


def test_cli_feature_set_validates_the_catalog_toggles_and_emits_events(seed, migrated, admin_url, monkeypatch):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(seed["A"])
    with pytest.raises(SystemExit, match="unknown feature"):
        cli.main(["feature-set", t, "invented", "on"])
    cli.main(["feature-set", t, "customer_context", "on"])
    with migrated.begin() as c:
        assert features.enabled(c, seed["A"], "customer_context") is True
    cli.main(["feature-set", t, "customer_context", "off"])
    with migrated.begin() as c:
        assert features.enabled(c, seed["A"], "customer_context") is False
    cli.main(["feature-set", t, "customer_context", "default"])
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM tenant_features WHERE feature = 'customer_context'")).scalar() == 0
        assert features.enabled(c, seed["A"], "customer_context") is False  # back to the code default
        ev = c.execute(text("SELECT count(*) FROM events_outbox WHERE event_type = 'tenant.feature.changed' AND tenant_id = :t"), {"t": seed["A"]}).scalar()
    assert ev >= 3
