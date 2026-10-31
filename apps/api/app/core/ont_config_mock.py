"""SYNTHETIC configuration profiles for the ONT Configuration Manager (ADR-0034): lab/demo/test data only, written by the owner CLI with source `mock` and labelled
as synthetic by every answer. None of it came from a device; the names, networks and addresses are invented. Every field goes through the same validation as an
Edge report."""
from __future__ import annotations

from app.core import ont_config

# (name, instance, value)
PROFILES: dict[str, list[tuple[str, str, object]]] = {
    # two radios, one SSID each, the usual home gateway
    "dualband": [
        ("wifi.radio.band", "radio/1", "2.4GHz"), ("wifi.radio.enabled", "radio/1", True), ("wifi.channel", "radio/1", 6), ("wifi.channel_auto", "radio/1", True),
        ("wifi.channel_width", "radio/1", "20MHz"), ("wifi.transmit_power", "radio/1", 100),
        ("wifi.radio.band", "radio/2", "5GHz"), ("wifi.radio.enabled", "radio/2", True), ("wifi.channel", "radio/2", 36), ("wifi.channel_auto", "radio/2", False),
        ("wifi.channel_width", "radio/2", "80MHz"),
        ("wifi.ssid", "ssid/1", "Rede_Demo_2G"), ("wifi.ssid.enabled", "ssid/1", True), ("wifi.ssid.radio", "ssid/1", "radio/1"), ("wifi.security_mode", "ssid/1", "WPA2-Personal"),
        ("wifi.password.set", "ssid/1", True),
        ("wifi.ssid", "ssid/5", "Rede_Demo_5G"), ("wifi.ssid.enabled", "ssid/5", True), ("wifi.ssid.radio", "ssid/5", "radio/2"), ("wifi.security_mode", "ssid/5", "WPA2-Personal"),
        ("wifi.password.set", "ssid/5", True),
        ("lan.ipv4_address", "lan/1", "192.168.1.1"), ("lan.netmask", "lan/1", "255.255.255.0"), ("lan.dhcp_enabled", "lan/1", True),
        ("lan.dhcp_min", "lan/1", "192.168.1.10"), ("lan.dhcp_max", "lan/1", "192.168.1.200"), ("lan.dns", "lan/1", "192.0.2.53,192.0.2.54"),
        ("wan.type", "wan/1", "ppp"), ("wan.status", "wan/1", "Connected"), ("wan.vlan_id", "wan/1", 100), ("wan.nat_enabled", "wan/1", True), ("wan.ipv6_enabled", "wan/1", False),
        ("wan.pppoe.password.set", "wan/1", True),
        ("optical.rx_dbm", "optical/1", -19.4), ("optical.tx_dbm", "optical/1", 2.1),
    ],
    # SSID numbers do NOT follow the band: ssid/3 is the 5 GHz one here, ssid/1 and ssid/2 share the 2.4 GHz radio (guest network)
    "multi_ssid": [
        ("wifi.radio.band", "radio/1", "2.4GHz"), ("wifi.radio.enabled", "radio/1", True), ("wifi.radio.band", "radio/2", "5GHz"), ("wifi.radio.enabled", "radio/2", True),
        ("wifi.ssid", "ssid/1", "Casa_Demo"), ("wifi.ssid.enabled", "ssid/1", True), ("wifi.ssid.radio", "ssid/1", "radio/1"),
        ("wifi.ssid", "ssid/2", "Casa_Demo_Visitas"), ("wifi.ssid.enabled", "ssid/2", False), ("wifi.ssid.radio", "ssid/2", "radio/1"),
        ("wifi.ssid", "ssid/3", "Casa_Demo_5G"), ("wifi.ssid.enabled", "ssid/3", True), ("wifi.ssid.radio", "ssid/3", "radio/2"),
        ("optical.rx_dbm", "optical/1", -21.0),
    ],
    # a bridge-mode device that exposes no Wi-Fi at all
    "no_wifi": [
        ("wan.type", "wan/1", "bridge"), ("wan.status", "wan/1", "Up"), ("lan.ipv4_address", "lan/1", "192.168.100.1"), ("lan.netmask", "lan/1", "255.255.255.0"),
        ("optical.rx_dbm", "optical/1", -18.2),
    ],
    # the 5 GHz radio exists but is switched off; the device did not report which band its SSID belongs to
    "inactive_5g": [
        ("wifi.radio.band", "radio/1", "2.4GHz"), ("wifi.radio.enabled", "radio/1", True), ("wifi.radio.enabled", "radio/2", False),
        ("wifi.ssid", "ssid/1", "Rede_Demo_2G"), ("wifi.ssid.enabled", "ssid/1", True), ("wifi.ssid.radio", "ssid/1", "radio/1"),
        ("wifi.ssid", "ssid/2", "Rede_Demo_5G"), ("wifi.ssid.enabled", "ssid/2", False),
        ("optical.rx_dbm", "optical/1", -20.0),
    ],
}


def rows_for(profile: str) -> list[tuple[str, str, object]]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; known: {', '.join(sorted(PROFILES))}")
    for name, inst, value in PROFILES[profile]:
        code = ont_config.check_field(name, inst, value)
        if code:
            raise ValueError(f"{profile}: {name} {inst}: {code}")
    return PROFILES[profile]
