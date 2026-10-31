"""ONT Configuration Manager, reading side (ADR-0034, FC24-01): the closed field catalog, ingestion from the Edge, capability discovery from what was observed, the dynamic
form schema, read-only everywhere, secrets never returned, tenant isolation and the flag. Everything is SYNTHETIC; nothing here talks to equipment."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.core import ont_config, ont_config_mock
from tests.conftest import _now, agent, hdr


@pytest.fixture(autouse=True, scope="module")
def _clean_up_after_the_module(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'CFG%'"))


@pytest.fixture
def on(migrated, seed):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'ont_config',true) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = true"), {"t": seed["A"]})
    yield
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM tenant_features WHERE tenant_id = :t AND feature = 'ont_config'"), {"t": seed["A"]})


def _cpe(client, inv, seed, serial, ext, key="a1", tenant="A", who="alice"):
    body = {"edge_id": str(inv[key]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": serial, "vendor": "ACME", "model": "G3000", "firmware": "1.0",
         "binding": {"protocol": "tr069", "external_id": ext, "connector_id": f"c-cfg-{key}"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, key), json=body).status_code == 202
    return next(c["id"] for c in client.get("/v1/cpes", headers=hdr(client, who, seed, tenant)).json() if c["canonical_serial"] == serial)


def _seed(migrated, seed, cpe, profile, tenant="A"):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed[tenant])})
        for name, inst, value in ont_config_mock.rows_for(profile):
            c.execute(text("INSERT INTO cpe_config_fields (tenant_id, cpe_id, name, instance_key, value, captured_at, observed_at, data_model, protocol, source) "
                           "VALUES (:t,:c,:n,:i,CAST(:v AS jsonb),now(),now(),'tr181','tr069','mock') ON CONFLICT DO NOTHING"),
                      {"t": seed[tenant], "c": cpe, "n": name, "i": inst, "v": json.dumps(value)})


def _f(name, instance, value, at=None):
    return {"name": name, "instance": instance, "value": value, "captured_at": at or _now(-30)}


def _report(inv, ext, fields, key="a1", observed=None, model="tr181"):
    return {"edge_id": str(inv[key]["edge"]), "observed_at": observed or _now(), "configs": [
        {"binding": {"protocol": "tr069", "external_id": ext, "connector_id": f"c-cfg-{key}"}, "data_model": model, "fields": fields}]}


def test_the_catalog_has_no_password_value_and_no_device_path():
    for name, spec in ont_config.FIELDS.items():
        assert name == spec.name and "." in name
        assert "password" not in name or name.endswith(".password.set")
        if name.endswith(".password.set"):
            assert spec.kind == ("bool",)           # a password exists only as "is one set?"
        assert not name.startswith(("InternetGatewayDevice", "Device."))
    assert {c.id for c in ont_config.CAPABILITIES if c.group == "optical"} == {"optical.rx_dbm.read", "optical.tx_dbm.read"}      # optical power: reads only, no write capability
    assert not [c for c in ont_config.CAPABILITIES if c.group == "optical" and c.write]
    assert ont_config.WRITES_ENABLED is False


def test_values_are_checked_against_their_field():
    ok = [("wifi.ssid", "ssid/1", "Minha rede"), ("wifi.channel", "radio/2", 36), ("lan.ipv4_address", "lan/1", "10.0.0.1"), ("optical.rx_dbm", "optical/1", -19.4),
          ("wifi.password.set", "ssid/1", True), ("wan.vlan_id", "wan/1", 4094), ("lan.dns", "lan/1", "192.0.2.1,192.0.2.2")]
    for n, i, v in ok:
        assert ont_config.check_field(n, i, v) is None, (n, i, v)
    bad = [("wifi.password", "ssid/1", "hunter2"), ("wifi.password.set", "ssid/1", "yes"), ("wifi.psk", "ssid/1", "x"), ("InternetGatewayDevice.X", "ssid/1", 1),
           ("wifi.ssid", "radio/1", "x"), ("wifi.ssid", "ssid/1", "x" * 33), ("wifi.ssid", "ssid/1", "bad\nname"), ("wifi.channel", "radio/1", 999), ("wifi.channel", "radio/1", True),
           ("wifi.channel", "radio/1", "6"), ("lan.ipv4_address", "lan/1", "999.1.1.1"), ("lan.ipv4_address", "lan/1", "::1"), ("lan.dns", "lan/1", "1.1.1.1;rm"),
           ("optical.rx_dbm", "optical/1", -200), ("optical.rx_dbm", "optical/1", float("nan")), ("wan.vlan_id", "wan/1", 5000), ("wifi.radio.band", "radio/1", "7GHz"),
           ("wifi.ssid.radio", "ssid/1", "ssid/2"), ("wifi.ssid", "ssid/x", "a"), ("wifi.ssid", "ssid/1234", "a")]
    for n, i, v in bad:
        assert ont_config.check_field(n, i, v) is not None, (n, i, v)


def test_nothing_is_visible_while_the_flag_is_off(client, seed, inv):
    cpe = _cpe(client, inv, seed, "CFG-OFF-1", "ext-cfg-off-1")
    h = hdr(client, "alice", seed, "A")
    for path in ("configuration", "capabilities", "form-schema"):
        assert client.get(f"/v1/cpes/{cpe}/ont-config/{path}", headers=h).status_code == 403
    ing = client.post("/v1/edge/cpe-config", headers=agent(client, inv, "a1"), json=_report(inv, "ext-cfg-off-1", [_f("wifi.ssid", "ssid/1", "x")]))
    assert ing.status_code == 403 and ing.json()["detail"] == "feature_disabled"      # nothing is collected while the module is off
    assert client.get("/v1/ont-config/health", headers=h).json() == {"enabled": False, "writes_enabled": False, "cpes_with_configuration": 0, "catalog_fields": len(ont_config.FIELDS)}


def test_an_unknown_device_has_no_data_and_the_form_is_empty_not_invented(client, seed, inv, on):
    cpe = _cpe(client, inv, seed, "CFG-EMPTY-1", "ext-cfg-empty-1")
    h = hdr(client, "alice", seed, "A")
    cfg = client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()
    assert cfg["state"] == "no_data" and cfg["fields"] == [] and cfg["observed_at"] is None and cfg["synthetic"] is False
    fs = client.get(f"/v1/cpes/{cpe}/ont-config/form-schema", headers=h).json()
    assert fs["state"] == "no_data" and fs["groups"] == [] and fs["editable"] is False
    caps = client.get(f"/v1/cpes/{cpe}/ont-config/capabilities", headers=h).json()
    assert caps["items"] and all(i["support"] == "unknown" and i["write_allowed"] is False and i["instances"] == [] for i in caps["items"])
    assert client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).status_code == 200


def test_dualband_discovery_form_and_secrets(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-DUAL-1", "ext-cfg-dual-1")
    _seed(migrated, seed, cpe, "dualband")
    h = hdr(client, "alice", seed, "A")
    cfg = client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()
    assert cfg["state"] == "fresh" and cfg["synthetic"] is True and cfg["sources"] == ["mock"] and len(cfg["revision"]) == 16
    names = {(f["name"], f["instance_key"]): f for f in cfg["fields"]}
    assert names[("wifi.ssid", "ssid/1")]["value"] == "Rede_Demo_2G" and all(f["writable"] is False for f in cfg["fields"])
    assert names[("wifi.password.set", "ssid/1")]["value"] == "definida" and names[("wifi.password.set", "ssid/1")]["secret"] is True
    assert names[("optical.rx_dbm", "optical/1")]["unit"] == "dBm"
    fs = client.get(f"/v1/cpes/{cpe}/ont-config/form-schema", headers=h).json()
    assert [g["id"] for g in fs["groups"]] == ["wifi", "lan", "wan", "optical"] and fs["form_revision"] == cfg["revision"] and fs["help_slug"] == "ont/consultar-configuracao"
    assert all(f["input_type"] == "readonly" and f["editable"] is False and f["disabled_reason"] for g in fs["groups"] for f in g["fields"])
    optical = next(g for g in fs["groups"] if g["id"] == "optical")
    assert optical["read_only"] is True and "medição" in optical["fields"][0]["disabled_reason"]
    ssid5 = next(f for g in fs["groups"] for f in g["fields"] if f["name"] == "wifi.ssid" and f["instance_key"] == "ssid/5")
    assert ssid5["instance_label"] == "Rede 5 GHz" and ssid5["value"] == "Rede_Demo_5G"       # the band comes from the radio the device bound it to
    blob = json.dumps([cfg, fs, client.get(f"/v1/cpes/{cpe}/ont-config/capabilities", headers=h).json()]).lower()
    assert "psk" not in blob and "hunter" not in blob and '"password"' not in blob and "keypassphrase" not in blob


def test_ssid_numbers_do_not_decide_the_band_and_unreported_bands_are_said_so(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-MULTI-1", "ext-cfg-multi-1")
    _seed(migrated, seed, cpe, "multi_ssid")
    h = hdr(client, "alice", seed, "A")
    inst = client.get(f"/v1/cpes/{cpe}/ont-config/form-schema", headers=h).json()["instances"]
    labels = {i["key"]: i["label"] for i in inst["ssid"]}
    assert labels == {"ssid/1": "Rede 2.4 GHz".replace("2.4 GHz", "2.4 GHz"), "ssid/2": "Rede 2.4 GHz", "ssid/3": "Rede 5 GHz"}
    cpe2 = _cpe(client, inv, seed, "CFG-INACT-1", "ext-cfg-inact-1")
    _seed(migrated, seed, cpe2, "inactive_5g")
    inst2 = client.get(f"/v1/cpes/{cpe2}/ont-config/form-schema", headers=h).json()["instances"]
    assert {i["key"]: i["label"] for i in inst2["ssid"]} == {"ssid/1": "Rede 2.4 GHz", "ssid/2": "Rede 2 (banda não informada)"}      # no guess from the position
    assert {i["key"]: i["label"] for i in inst2["radio"]} == {"radio/1": "Rádio 2.4 GHz", "radio/2": "Rádio 2 (banda não informada)"}


def test_no_wifi_device_shows_no_wifi_group_and_no_wifi_capability(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-NOWIFI-1", "ext-cfg-nowifi-1")
    _seed(migrated, seed, cpe, "no_wifi")
    h = hdr(client, "alice", seed, "A")
    fs = client.get(f"/v1/cpes/{cpe}/ont-config/form-schema", headers=h).json()
    assert [g["id"] for g in fs["groups"]] == ["lan", "wan", "optical"]
    caps = {i["capability"]: i for i in client.get(f"/v1/cpes/{cpe}/ont-config/capabilities", headers=h).json()["items"]}
    assert caps["wifi.ssid.read"]["support"] == "unknown" and caps["lan.ipv4.read"]["support"] == "supported" and caps["optical.rx_dbm.read"]["support"] == "supported"


def test_capabilities_say_what_was_observed_and_nothing_is_writable(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-CAPS-1", "ext-cfg-caps-1")
    _seed(migrated, seed, cpe, "dualband")
    h = hdr(client, "alice", seed, "A")
    body = client.get(f"/v1/cpes/{cpe}/ont-config/capabilities", headers=h).json()
    caps = {i["capability"]: i for i in body["items"]}
    assert body["writes_enabled"] is False and body["synthetic"] is True and caps["wifi.ssid.write"]["device_fingerprint"] == {"vendor": "ACME", "model": "G3000", "firmware": "1.0"}
    assert caps["wifi.ssid.read"]["support"] == "supported" and caps["wifi.ssid.read"]["certification"] == "observed_read"
    assert {i["key"] for i in caps["wifi.ssid.read"]["instances"]} == {"ssid/1", "ssid/5"}
    assert all(i["write_allowed"] is False for i in body["items"])
    assert caps["wifi.ssid.write"]["write_blocked_reason"] == "writes_not_enabled" and caps["optical.rx_dbm.read"]["write_blocked_reason"] == "read_only"
    assert caps["wifi.transmit_power.read"]["support"] == "supported" and caps["wifi.transmit_power.read"]["unit"] is None      # raw value: no unit is assumed
    assert caps["lan.ipv4.write"]["risk"] == "R3" and caps["wifi.ssid.write"]["risk"] == "R1" and caps["wifi.password.write"]["risk"] == "R2"
    # even a certified registry entry does not open a write in this delivery
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, verified_at, evidence_ref) "
                       "VALUES (:t,'ACME','G3000','1.0','tr069','set_wifi_ssid','supported','observed', now(), 'docs/wiki/bench/x.md') ON CONFLICT DO NOTHING"), {"t": seed["A"]})
    again = {i["capability"]: i for i in client.get(f"/v1/cpes/{cpe}/ont-config/capabilities", headers=h).json()["items"]}
    assert again["wifi.ssid.write"]["certification"] == "certified_write" and again["wifi.ssid.write"]["write_allowed"] is False
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM device_capabilities WHERE vendor = 'ACME' AND model = 'G3000' AND operation = 'set_wifi_ssid'"))


def test_stale_data_is_marked_and_a_silent_source_is_reported(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-STALE-1", "ext-cfg-stale-1")
    _seed(migrated, seed, cpe, "dualband")
    h = hdr(client, "alice", seed, "A")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE cpe_config_fields SET captured_at = now() - interval '3 hours' WHERE cpe_id = :c AND name = 'wifi.ssid'"), {"c": cpe})
    cfg = client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()
    assert cfg["state"] == "partial_stale" and {f["quality"] for f in cfg["fields"] if f["name"] == "wifi.ssid"} == {"stale"}
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE cpe_config_fields SET captured_at = now() - interval '2 days' WHERE cpe_id = :c"), {"c": cpe})
    assert client.get(f"/v1/cpes/{cpe}/ont-config/form-schema", headers=h).json()["state"] == "stale"


def test_the_edge_reports_validated_fields_and_the_newest_device_time_wins(client, seed, inv, on):
    cpe = _cpe(client, inv, seed, "CFG-EDGE-1", "ext-cfg-edge-1")
    h, ag = hdr(client, "alice", seed, "A"), agent(client, inv, "a1")
    first = _report(inv, "ext-cfg-edge-1", [_f("wifi.ssid", "ssid/1", "Primeiro", _now(-120)), _f("wifi.radio.band", "radio/1", "2.4GHz", _now(-120))])
    r = client.post("/v1/edge/cpe-config", headers=ag, json=first)
    assert r.status_code == 202 and r.json() == {"status": "accepted", "cpes": 1, "fields": 2, "unknown": 0}
    newer = _report(inv, "ext-cfg-edge-1", [_f("wifi.ssid", "ssid/1", "Segundo", _now(-60))])
    older = _report(inv, "ext-cfg-edge-1", [_f("wifi.ssid", "ssid/1", "Antigo", _now(-600))])
    assert client.post("/v1/edge/cpe-config", headers=ag, json=newer).status_code == 202
    assert client.post("/v1/edge/cpe-config", headers=ag, json=older).status_code == 202      # a replay of an older read is accepted and ignored
    cfg = client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()
    ssid = next(f for f in cfg["fields"] if f["name"] == "wifi.ssid")
    assert ssid["value"] == "Segundo" and ssid["source"] == "edge" and cfg["synthetic"] is False


def test_ingestion_refuses_anything_outside_the_catalog(client, seed, inv, on):
    _cpe(client, inv, seed, "CFG-BAD-1", "ext-cfg-bad-1")
    ag = agent(client, inv, "a1")
    bad = [_f("wifi.password", "ssid/1", "hunter2"), _f("InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.PreSharedKey.1.KeyPassphrase", "ssid/1", "x"),
           _f("wifi.ssid", "ssid/1", "x" * 40), _f("wifi.channel", "radio/1", 5000), _f("wifi.password.set", "ssid/1", "secret-value"), _f("wifi.ssid", "lan/1", "a"),
           _f("optical.rx_dbm", "optical/1", 99), _f("lan.ipv4_address", "lan/1", "not-an-ip")]
    for f in bad:
        assert client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-bad-1", [f])).status_code == 422, f
    assert client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-bad-1", [{**_f("wifi.ssid", "ssid/1", "a"), "extra": 1}])).status_code == 422
    assert client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-bad-1", [_f("wifi.ssid", "ssid/1", "a", _now(86400))])).status_code == 422      # a device time in the future
    # a human token cannot report; the report must come from the Edge that owns the CPE
    assert client.post("/v1/edge/cpe-config", headers=hdr(client, "alice", seed, "A"), json=_report(inv, "ext-cfg-bad-1", [_f("wifi.ssid", "ssid/1", "a")])).status_code == 403


def test_another_edge_or_tenant_cannot_report_or_read(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-ISO-1", "ext-cfg-iso-1")
    _seed(migrated, seed, cpe, "dualband")
    other_edge = client.post("/v1/edge/cpe-config", headers=agent(client, inv, "a2"), json=_report(inv, "ext-cfg-iso-1", [_f("wifi.ssid", "ssid/1", "Intruso")], key="a2"))
    assert other_edge.status_code == 202 and other_edge.json()["unknown"] == 1 and other_edge.json()["fields"] == 0       # indistinguishable from an unknown CPE
    assert client.post("/v1/edge/cpe-config", headers=agent(client, inv, "a1"), json=_report(inv, "ext-cfg-iso-1", [_f("wifi.ssid", "ssid/1", "x")], key="b1")).status_code == 403
    bob, h = hdr(client, "bob", seed, "B"), hdr(client, "alice", seed, "A")
    assert client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=bob).status_code in (403, 404)       # B's flag is off; and the row is invisible to B anyway
    ssid = next(f for f in client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()["fields"] if f["name"] == "wifi.ssid" and f["instance_key"] == "ssid/1")
    assert ssid["value"] == "Rede_Demo_2G"


def test_permissions_and_the_audit_of_a_view(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-RBAC-1", "ext-cfg-rbac-1")
    _seed(migrated, seed, cpe, "dualband")
    assert client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=hdr(client, "dave", seed, "A")).status_code == 200      # NOC N1 reads (inventory:read)
    assert client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=hdr(client, "carol", seed, "A")).status_code == 403      # the auditor does not read device configuration
    assert client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers={}).status_code == 401
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        ev = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE action = 'cpe.config.viewed' AND target_id = :c ORDER BY created_at DESC LIMIT 1"), {"c": str(cpe)}).scalar()
    assert ev == {"fields": len(ont_config_mock.rows_for("dualband"))}      # who looked and how much; never the values


def test_the_confirmed_onu_link_brings_the_optical_power_from_the_olt_read_only(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-OPT-1", "ext-cfg-opt-1")
    h = hdr(client, "alice", seed, "A")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        edge = inv["a1"]["edge"]
        olt = c.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, model, firmware, support_level, observed_at) VALUES (:t,:e,'OLT-CFG-OPT','huawei','MA5608T','R015','identified',now()) RETURNING id"),
                        {"t": seed["A"], "e": edge}).scalar()
        onu = c.execute(text("INSERT INTO onus (tenant_id, olt_id, serial, status, rx_dbm, observed_at) VALUES (:t,:o,'48575443CFG00001','online',-17.5,now()) RETURNING id"),
                        {"t": seed["A"], "o": olt}).scalar()
        c.execute(text("INSERT INTO onu_cpe_links (tenant_id, onu_id, cpe_id, status, confidence, evidence, reviewed_by, reviewed_at) VALUES (:t,:u,:c,'confirmed',1,CAST('{\"rule\":\"test\"}' AS jsonb),:r,now())"),
                  {"t": seed["A"], "u": onu, "c": cpe, "r": seed["alice"]})
    fs = client.get(f"/v1/cpes/{cpe}/ont-config/form-schema", headers=h).json()
    opt = next(f for g in fs["groups"] if g["id"] == "optical" for f in g["fields"])
    assert opt["name"] == "optical.rx_dbm" and opt["value"] == -17.5 and opt["source"] == "olt" and opt["editable"] is False and opt["unit"] == "dBm"
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM onu_cpe_links WHERE cpe_id = :c"), {"c": cpe})
        c.execute(text("DELETE FROM onus WHERE id = :o"), {"o": onu})
        c.execute(text("DELETE FROM olts WHERE id = :o"), {"o": olt})


def test_the_database_itself_refuses_a_password_value_and_a_foreign_tenant(client, seed, inv, on, migrated):
    cpe = _cpe(client, inv, seed, "CFG-DB-1", "ext-cfg-db-1")
    for name in ("wifi.password", "wifi.psk_password", "wan.pppoe.password"):
        with pytest.raises(Exception, match="check|violates"):
            with migrated.begin() as c:
                c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
                c.execute(text("INSERT INTO cpe_config_fields (tenant_id, cpe_id, name, instance_key, value, captured_at, observed_at, data_model, protocol, source) "
                               "VALUES (:t,:c,:n,'ssid/1','\"x\"',now(),now(),'tr181','tr069','edge')"), {"t": seed["A"], "c": cpe, "n": name})
    with pytest.raises(Exception, match="foreign key|violates"):
        with migrated.begin() as c:
            c.execute(text("INSERT INTO cpe_config_fields (tenant_id, cpe_id, name, instance_key, value, captured_at, observed_at, data_model, protocol, source) "
                           "VALUES (:t,:c,'wifi.ssid','ssid/1','\"x\"',now(),now(),'tr181','tr069','edge')"), {"t": seed["B"], "c": cpe})      # B cannot attach a row to A's CPE


def test_the_owner_cli_writes_and_clears_a_labelled_synthetic_profile(client, seed, inv, on, migrated, monkeypatch):
    from app import cli
    cpe = _cpe(client, inv, seed, "CFG-CLI-1", "ext-cfg-cli-1")
    h = hdr(client, "alice", seed, "A")
    monkeypatch.setenv("ADMIN_DATABASE_URL", str(migrated.url.render_as_string(hide_password=False)))
    cli.main(["ont-config-mock", str(seed["A"]), str(cpe), "multi_ssid"])
    cfg = client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()
    assert cfg["synthetic"] is True and len(cfg["fields"]) == len(ont_config_mock.rows_for("multi_ssid"))
    cli.main(["ont-config-mock", str(seed["A"]), str(cpe), "clear"])
    assert client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()["fields"] == []
    with pytest.raises(SystemExit):
        cli.main(["ont-config-mock", str(seed["A"]), str(cpe), "nope"])
    with pytest.raises(SystemExit):
        cli.main(["ont-config-mock", str(seed["B"]), str(cpe), "dualband"])      # a CPE of another tenant is not found


def test_the_revision_changes_only_when_the_configuration_changes():
    rows = [{"name": "wifi.ssid", "instance_key": "ssid/1", "value": "A"}, {"name": "wifi.channel", "instance_key": "radio/1", "value": 6}]
    r1 = ont_config.revision(rows)
    assert r1 == ont_config.revision(list(reversed(rows))) and r1 != ont_config.revision([{**rows[0], "value": "B"}, rows[1]])


def test_a_field_cannot_be_newer_than_its_snapshot_nor_than_the_cloud_clock(client, seed, inv, on):
    cpe = _cpe(client, inv, seed, "CFG-CLK-1", "ext-cfg-clk-1")
    h, ag = hdr(client, "alice", seed, "A"), agent(client, inv, "a1")
    ahead = _report(inv, "ext-cfg-clk-1", [_f("wifi.ssid", "ssid/1", "Adiantado", _now(240))], observed=_now(-10))      # 4 min ahead of a snapshot taken 10 s ago
    assert client.post("/v1/edge/cpe-config", headers=ag, json=ahead).status_code == 422
    skewed = _report(inv, "ext-cfg-clk-1", [_f("wifi.ssid", "ssid/1", "Relogio_rapido", _now(200))], observed=_now(200))      # an Edge whose whole clock runs 200 s fast
    assert client.post("/v1/edge/cpe-config", headers=ag, json=skewed).status_code == 202
    right = _report(inv, "ext-cfg-clk-1", [_f("wifi.ssid", "ssid/1", "Correto", _now(-5))])
    assert client.post("/v1/edge/cpe-config", headers=ag, json=right).status_code == 202
    ssid = next(f for f in client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()["fields"] if f["name"] == "wifi.ssid")
    assert ssid["captured_at"] <= _now() and ssid["value"] in ("Relogio_rapido", "Correto")      # stored time never runs ahead of the cloud clock


def test_a_repeated_field_in_one_batch_keeps_the_newest_and_does_not_break_the_rest(client, seed, inv, on):
    cpe = _cpe(client, inv, seed, "CFG-DUP-1", "ext-cfg-dup-1")
    h, ag = hdr(client, "alice", seed, "A"), agent(client, inv, "a1")
    twice = _report(inv, "ext-cfg-dup-1", [_f("wifi.ssid", "ssid/1", "Velho", _now(-100)), _f("wifi.ssid", "ssid/1", "Novo", _now(-20)), _f("wifi.channel", "radio/1", 11, _now(-20))])
    twice["configs"].append(_report(inv, "ext-cfg-dup-1", [_f("wifi.ssid", "ssid/1", "Mais_velho", _now(-300))])["configs"][0])      # the same CPE listed twice in the snapshot
    r = client.post("/v1/edge/cpe-config", headers=ag, json=twice)
    assert r.status_code == 202 and r.json()["fields"] == 2
    got = {f["name"]: f["value"] for f in client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()["fields"]}
    assert got == {"wifi.ssid": "Novo", "wifi.channel": 11}


def test_conflicting_observations_with_the_same_device_time_are_refused_in_any_order(client, seed, inv, on):
    _cpe(client, inv, seed, "CFG-TIE-1", "ext-cfg-tie-1")
    ag, at = agent(client, inv, "a1"), _now(-30)
    for first, second in (("A", "B"), ("B", "A")):
        r = client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-tie-1", [_f("wifi.ssid", "ssid/1", first, at), _f("wifi.ssid", "ssid/1", second, at)]))
        assert r.status_code == 422 and r.json()["detail"] == "conflicting_observations"
    same = client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-tie-1", [_f("wifi.ssid", "ssid/1", "A", at), _f("wifi.ssid", "ssid/1", "A", at)]))
    assert same.status_code == 202 and same.json()["fields"] == 1      # the same value twice is just a repeat


def test_a_tie_with_the_stored_observation_is_refused_too_and_nothing_of_the_batch_is_kept(client, seed, inv, on):
    cpe = _cpe(client, inv, seed, "CFG-TIE-2", "ext-cfg-tie-2")
    h, ag, at = hdr(client, "alice", seed, "A"), agent(client, inv, "a1"), _now(-30)
    assert client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-tie-2", [_f("wifi.ssid", "ssid/1", "A", at)])).status_code == 202
    r = client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-tie-2", [_f("wifi.channel", "radio/1", 6, at), _f("wifi.ssid", "ssid/1", "B", at)]))
    assert r.status_code == 422 and r.json()["detail"] == "conflicting_observations"
    got = {f["name"]: f["value"] for f in client.get(f"/v1/cpes/{cpe}/ont-config/configuration", headers=h).json()["fields"]}
    assert got == {"wifi.ssid": "A"}      # the channel of the refused batch was rolled back with it
    assert client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-tie-2", [_f("wifi.ssid", "ssid/1", "A", at)])).status_code == 202      # the same value again is a repeat
    import threading
    codes = []
    def go(v):
        codes.append(client.post("/v1/edge/cpe-config", headers=ag, json=_report(inv, "ext-cfg-tie-2", [_f("wifi.channel", "radio/1", v, _now(-10))])).status_code)
    ts = [threading.Thread(target=go, args=(6 + (i % 2) * 5,)) for i in range(2)]      # two requests with the SAME device time: 6 and 11
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) in ([202, 202], [202, 422]), codes
