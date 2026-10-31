"""ONT Configuration Manager, preview of a change (ADR-0036, FC24-03): validation, diff, risk/approvals, the ordered blockers and the fact that NOTHING executes.
Everything is synthetic; no test talks to equipment."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core import ont_config
from app.core import ont_config_changes as chg
from tests.conftest import hdr
from tests.test_ont_config import _cpe, _seed


@pytest.fixture(autouse=True, scope="module")
def _clean_up_after_the_module(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'CHG%'"))


@pytest.fixture
def on(migrated, seed):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'ont_config',true) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = true"), {"t": seed["A"]})
    yield
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM tenant_features WHERE tenant_id = :t AND feature = 'ont_config'"), {"t": seed["A"]})


@pytest.fixture
def cpe(client, inv, seed, migrated, on, request):
    serial = "CHG" + request.node.name.upper().replace("_", "")[:20]
    c = _cpe(client, inv, seed, serial, "ext-" + serial)
    _seed(migrated, seed, c, "dualband")
    return c


def _rev(client, seed, cpe, who="alice"):
    return client.get(f"/v1/cpes/{cpe}/ont-config/form-schema", headers=hdr(client, who, seed, "A")).json()["form_revision"]


def _preview(client, seed, cpe, capability, instance, params, who="alice", rev=None):
    body = {"capability": capability, "instance_key": instance, "params": params, "if_match": rev or _rev(client, seed, cpe)}
    return client.post(f"/v1/cpes/{cpe}/ont-config/changes/preview", headers=hdr(client, who, seed, "A"), json=body)


def test_preview_describes_the_change_and_is_never_submittable(client, seed, cpe):
    r = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova_Rede"})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["executes"] is False and b["submittable"] is False and b["risk"] == "R1" and b["status"] == "previewed"
    assert b["diff"] == [{"field": "wifi.ssid", "label": "Nome da rede", "from": "Rede_Demo_2G", "to": "Nova_Rede", "secret": False, "changes": True}]
    assert b["approvals"] == chg.APPROVALS["R1"]
    # fixed order, and the synthetic source is one of the reasons
    assert b["blockers"][0] == "writes_not_enabled" and b["blockers"][-1] == "executor_not_available"
    assert {"capability_not_certified", "synthetic_source"} <= set(b["blockers"])
    got = client.get(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}", headers=hdr(client, "alice", seed, "A"))
    assert got.status_code == 200 and got.json()["intent_hash"] == b["intent_hash"]


def test_submit_never_executes_and_records_the_block(client, seed, cpe, migrated):
    b = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova_Rede"}).json()
    r = client.post(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}/submit", headers=hdr(client, "alice", seed, "A"))
    assert r.status_code == 409 and r.json()["executed"] is False and r.json()["detail"] == "writes_not_enabled"
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert c.execute(text("SELECT status FROM cpe_config_changes WHERE id = :i"), {"i": b["id"]}).scalar() == "blocked"
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'ont_config.change_blocked' AND evidence_redacted->>'change_id' = :i"), {"i": b["id"]}).scalar() == 1


def test_submit_creates_no_job(client, seed, cpe, migrated):
    def n():
        with migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            return c.execute(text("SELECT count(*) FROM jobs")).scalar()
    before = n()
    b = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova_Rede"}).json()
    client.post(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}/submit", headers=hdr(client, "alice", seed, "A"))
    assert n() == before


def test_even_with_everything_else_ready_the_missing_executor_still_blocks(client, seed, cpe, migrated, monkeypatch):
    monkeypatch.setattr(ont_config, "WRITES_ENABLED", True)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE cpe_config_fields SET source = 'edge' WHERE cpe_id = :c"), {"c": cpe})
    b = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova_Rede"}).json()
    assert "writes_not_enabled" not in b["blockers"] and "synthetic_source" not in b["blockers"] and "stale_data" not in b["blockers"]
    assert b["blockers"][-1] == "executor_not_available" and b["submittable"] is False
    r = client.post(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}/submit", headers=hdr(client, "alice", seed, "A"))
    assert r.status_code == 409 and r.json()["executed"] is False


@pytest.mark.parametrize("cap,inst,params,code", [
    ("wifi.ssid.write", "ssid/1", {"wifi.ssid": "x" * 33}, "value_not_valid_for_field"),
    ("wifi.ssid.write", "radio/1", {"wifi.ssid": "Ok"}, "instance_not_valid_for_field"),
    ("wifi.ssid.write", "ssid/1", {"wifi.channel": 6}, "field_not_allowed_for_capability"),
    ("wifi.ssid.write", "ssid/1", {}, "field_not_allowed_for_capability"),
    ("wifi.ssid.write", "ssid/9", {"wifi.ssid": "Ok"}, "instance_not_observed"),
    ("wifi.channel.write", "radio/1", {"wifi.channel": 400}, "value_not_valid_for_field"),
    ("lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.0.0.1"}, "fields_must_come_together"),
    ("lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.0.0.255", "lan.netmask": "255.255.255.0"}, "address_not_a_host"),
    ("lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.0.0.1", "lan.netmask": "255.0.255.0"}, "netmask_not_contiguous"),
    ("lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.0.0.1", "lan.netmask": "255.255.255.254"}, "address_not_a_host"),
    ("lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.0.0.1", "lan.netmask": "255.255.255.255"}, "address_not_a_host"),
    ("lan.dhcp.write", "lan/1", {"lan.dhcp_min": "10.0.0.50", "lan.dhcp_max": "10.0.0.10"}, "dhcp_range_inverted"),
    ("lan.dhcp.write", "lan/1", {"lan.dhcp_min": "192.168.2.10", "lan.dhcp_max": "192.168.2.50"}, "dhcp_range_outside_subnet"),
    ("lan.dhcp.write", "lan/1", {"lan.dhcp_min": "192.168.1.1", "lan.dhcp_max": "192.168.1.50"}, "dhcp_range_outside_subnet"),
    ("lan.dhcp.write", "lan/1", {"lan.dhcp_min": "192.168.1.10", "lan.dhcp_max": "192.168.1.255"}, "dhcp_range_outside_subnet"),
    ("wifi.password.write", "ssid/1", {"wifi.password.set": "hunter2hunter2"}, "value_not_valid_for_field"),
    ("optical.rx_dbm.write", "optical/1", {"optical.rx_dbm": -10.0}, "unknown_capability"),
    ("wifi.ssid.write", "ssid/1", {"wifi.ssid": "Rede_Demo_2G"}, "no_change"),
])
def test_invalid_requests_are_refused_with_a_stable_code(client, seed, cpe, cap, inst, params, code):
    r = _preview(client, seed, cpe, cap, inst, params, who="alice")
    assert r.status_code == 422 and r.json()["detail"] == code, r.text


def test_the_password_is_never_accepted_stored_or_echoed(client, seed, cpe, migrated):
    r = _preview(client, seed, cpe, "wifi.password.write", "ssid/1", {"wifi.password.set": True})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["diff"][0]["secret"] is True and b["diff"][0]["to"] == "nova senha (valor não exibido)" and "secret_channel_not_available" in b["blockers"]
    # a value in place of the boolean is refused (the 422 body does not echo it back either)
    r2 = _preview(client, seed, cpe, "wifi.password.write", "ssid/1", {"wifi.password.set": "hunter2hunter2"})
    assert r2.status_code == 422 and "hunter2" not in r2.text
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert "hunter2" not in str(c.execute(text("SELECT params::text || diff::text FROM cpe_config_changes WHERE id = :i"), {"i": b["id"]}).scalar())


def test_stale_revision_is_a_conflict(client, seed, cpe):
    r = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova_Rede"}, rev="0" * 16)
    assert r.status_code == 409 and r.json()["detail"] == "stale_revision"


def test_risk_decides_the_approvals_and_r3_needs_its_own_permission(client, seed, cpe, monkeypatch):
    from app.core import security
    # noc_n1 (dave) only reads today; give it ONLY the low tier to prove the tiers are separate
    monkeypatch.setitem(security.ROLE_PERMISSIONS, "noc_n1", frozenset(security.ROLE_PERMISSIONS["noc_n1"] | {"ont_config:request"}))
    lan = _preview(client, seed, cpe, "lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.10.0.1", "lan.netmask": "255.255.255.0"}, who="alice")
    assert lan.status_code == 201 and lan.json()["risk"] == "R3" and lan.json()["approvals"] == chg.APPROVALS["R3"]
    assert lan.json()["approvals"]["recovery_plan_required"] is True
    ch = _preview(client, seed, cpe, "wifi.channel.write", "radio/1", {"wifi.channel": 11}, who="alice")
    assert ch.json()["risk"] == "R2" and ch.json()["approvals"]["distinct_from_requester"] is True
    assert _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Outra"}, who="dave").status_code == 201
    assert _preview(client, seed, cpe, "lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.10.0.1", "lan.netmask": "255.255.255.0"}, who="dave").status_code == 403


def test_roles_flag_and_tenant_isolation(client, seed, cpe, migrated, monkeypatch):
    assert _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova"}, who="carol").status_code == 403   # auditor
    assert _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova"}, who="dave").status_code == 403    # noc_n1 reads, does not ask
    b = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova"}).json()
    other = client.get(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}", headers=hdr(client, "bob", seed, "B"))
    assert other.status_code in (403, 404)
    # only the requester may submit
    from app.core import security
    monkeypatch.setitem(security.ROLE_PERMISSIONS, "noc_n1", frozenset(security.ROLE_PERMISSIONS["noc_n1"] | {"ont_config:request"}))
    r = client.post(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}/submit", headers=hdr(client, "dave", seed, "A"))
    assert r.status_code == 403
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE tenant_id = :t AND feature = 'ont_config'"), {"t": seed["A"]})
    off = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova"}, rev="0" * 16)
    assert off.status_code == 403 and off.json()["detail"] == "feature_disabled"


def test_an_expired_preview_cannot_be_submitted(client, seed, cpe, migrated):
    b = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova_Rede"}).json()
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE cpe_config_changes SET created_at = now() - interval '2 hours', expires_at = now() - interval '1 hour' WHERE id = :i"), {"i": b["id"]})
    assert client.get(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}", headers=hdr(client, "alice", seed, "A")).json()["status"] == "expired"
    r = client.post(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}/submit", headers=hdr(client, "alice", seed, "A"))
    assert r.status_code == 410


def test_a_change_of_the_configuration_after_the_preview_shows_as_stale_revision_on_submit(client, seed, cpe, migrated):
    b = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova_Rede"}).json()
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE cpe_config_fields SET value = '\"Mudou_Fora\"'::jsonb WHERE cpe_id = :c AND name = 'wifi.ssid' AND instance_key = 'ssid/1'"), {"c": cpe})
    r = client.post(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}/submit", headers=hdr(client, "alice", seed, "A"))
    assert r.status_code == 409 and "stale_revision" in r.json()["blockers"]


def test_every_write_capability_has_a_closed_field_list_inside_the_catalog():
    for cap, (names, _) in chg.WRITE_FIELDS.items():
        assert set(names) <= set(ont_config.FIELDS), cap
        assert not any(n.startswith("optical.") for n in names)


def test_r3_asks_for_a_recent_second_factor_when_the_platform_enforces_it(client, seed, cpe, monkeypatch):
    from app.core import settings
    body = ("lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.10.0.1", "lan.netmask": "255.255.255.0"})
    rev = _rev(client, seed, cpe)
    monkeypatch.setenv("MFA_RECENT_ENFORCE", "true")
    settings.get_settings.cache_clear()
    try:
        r = _preview(client, seed, cpe, *body, rev=rev)
        assert (r.status_code, r.json()["detail"]) == (403, "mfa_recent_required")
        # R1/R2 (Wi-Fi) do not need it
        assert _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova"}, rev=rev).status_code == 201
    finally:
        monkeypatch.setenv("MFA_RECENT_ENFORCE", "false")
        settings.get_settings.cache_clear()


def test_dhcp_range_is_judged_against_the_gateway_and_a_new_subnet_only_warns(client, seed, cpe, migrated):
    ok = _preview(client, seed, cpe, "lan.dhcp.write", "lan/1", {"lan.dhcp_min": "192.168.1.20", "lan.dhcp_max": "192.168.1.90"})
    assert ok.status_code == 201 and ok.json()["warnings"] == []
    # a new subnet that strands the CURRENT range is allowed to be previewed (otherwise the subnet could never change) but is flagged
    w = _preview(client, seed, cpe, "lan.ipv4.write", "lan/1", {"lan.ipv4_address": "10.10.0.1", "lan.netmask": "255.255.255.0"})
    assert w.status_code == 201 and w.json()["warnings"] == ["dhcp_range_outside_new_subnet"]
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE cpe_config_fields SET value = '\"192.168.1.100\"'::jsonb WHERE cpe_id = :c AND name = 'lan.ipv4_address'"), {"c": cpe})
    r = _preview(client, seed, cpe, "lan.dhcp.write", "lan/1", {"lan.dhcp_min": "192.168.1.20", "lan.dhcp_max": "192.168.1.90"})
    assert r.status_code == 201   # range below the gateway: fine
    r = _preview(client, seed, cpe, "lan.dhcp.write", "lan/1", {"lan.dhcp_min": "192.168.1.20", "lan.dhcp_max": "192.168.1.200"})
    assert r.status_code == 422 and r.json()["detail"] == "dhcp_range_contains_gateway"


def test_a_repeated_submission_is_answered_but_audited_once(client, seed, cpe, migrated):
    b = _preview(client, seed, cpe, "wifi.ssid.write", "ssid/1", {"wifi.ssid": "Nova_Rede"}).json()
    h = hdr(client, "alice", seed, "A")
    first = client.post(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}/submit", headers=h)
    again = client.post(f"/v1/cpes/{cpe}/ont-config/changes/{b['id']}/submit", headers=h)
    assert first.status_code == again.status_code == 409 and first.json() == again.json()
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'ont_config.change_blocked' AND evidence_redacted->>'change_id' = :i"), {"i": b["id"]}).scalar() == 1


def test_changing_one_dhcp_end_needs_the_other_end_known(client, seed, cpe, migrated):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM cpe_config_fields WHERE cpe_id = :c AND name = 'lan.dhcp_max'"), {"c": cpe})
    r = _preview(client, seed, cpe, "lan.dhcp.write", "lan/1", {"lan.dhcp_min": "192.168.1.20"})
    assert r.status_code == 422 and r.json()["detail"] == "dhcp_range_incomplete"
    ok = _preview(client, seed, cpe, "lan.dhcp.write", "lan/1", {"lan.dhcp_min": "192.168.1.20", "lan.dhcp_max": "192.168.1.90"})
    assert ok.status_code == 201


@pytest.mark.parametrize("addr,mask", [("192.168.1.100", "255.255.255.0"),      # the new gateway sits INSIDE the current range
                                       ("192.168.1.129", "255.255.255.128"),    # the whole current range falls outside the new subnet
                                       ("192.168.1.1", "255.255.255.128")])     # range 20-90 fits, but the old end 200 does not
def test_a_new_subnet_that_breaks_the_current_dhcp_range_is_flagged(client, seed, cpe, addr, mask):
    w = _preview(client, seed, cpe, "lan.ipv4.write", "lan/1", {"lan.ipv4_address": addr, "lan.netmask": mask})
    assert w.status_code == 201 and w.json()["warnings"] == ["dhcp_range_outside_new_subnet"], w.text
