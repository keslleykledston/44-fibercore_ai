"""ONT Configuration Manager, reading side (ADR-0034, FC24-01): the CLOSED catalog of configuration fields, the capability discovery derived from what was actually
observed, and the dynamic form schema. Nothing here reaches equipment and nothing here is a TR-069/USP path: the Edge maps device paths to these canonical names; the
cloud only accepts, validates and presents them.

Rules: (1) a field exists only if it was observed (no observation = `unknown`, never a guess); (2) a password is never a value: only "is one set?" as a boolean;
(3) optical power is read-only by construction (there is no write capability for it); (4) in this delivery NOTHING is editable (`write_allowed` is false for every
capability, with the reason), writes arrive with preview/approval/homologation (FC24-03/04)."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

FRESH_FOR = timedelta(hours=1)        # a display hint, like cpe_state
STALE_ALL_AFTER = timedelta(hours=24)  # nothing newer than this: the ACS/Edge is not delivering, say so

BANDS = ("2.4GHz", "5GHz", "6GHz")
_CONN = ("Unconfigured", "Connecting", "Connected", "PendingDisconnect", "Disconnecting", "Disconnected", "Up", "Down", "Dormant", "NotPresent", "LowerLayerDown", "Error", "Unknown")
SECURITY = ("None", "WEP", "WPA-Personal", "WPA2-Personal", "WPA3-Personal", "WPA-WPA2-Personal", "WPA2-WPA3-Personal", "WPA2-Enterprise")
WIDTHS = ("20MHz", "40MHz", "80MHz", "160MHz", "Auto")
_SSID = re.compile(r"^[^\x00-\x1f\x7f]{1,32}$")
_DNS = re.compile(r"^[0-9.]{7,15}(,[0-9.]{7,15}){0,2}$")


@dataclass(frozen=True)
class Field:
    name: str
    scope: str            # instance prefix: radio | ssid | lan | wan | optical
    kind: tuple           # ("bool",) | ("enum", values) | ("int", lo, hi) | ("float", lo, hi) | ("ssid",) | ("ipv4",) | ("dns",) | ("ref", prefix)
    group: str            # wifi | lan | wan | optical
    label: str
    unit: str | None = None


def _f(name, scope, kind, group, label, unit=None):
    return name, Field(name, scope, kind, group, label, unit)


FIELDS: dict[str, Field] = dict([
    _f("wifi.radio.band", "radio", ("enum", BANDS), "wifi", "Banda"),
    _f("wifi.radio.enabled", "radio", ("bool",), "wifi", "Rádio ligado"),
    _f("wifi.channel", "radio", ("int", 0, 196), "wifi", "Canal"),
    _f("wifi.channel_auto", "radio", ("bool",), "wifi", "Canal automático"),
    _f("wifi.channel_width", "radio", ("enum", WIDTHS), "wifi", "Largura do canal"),
    _f("wifi.transmit_power", "radio", ("int", 0, 1000), "wifi", "Potência Wi-Fi (valor bruto do aparelho)"),   # unit/range unknown until certified: raw
    _f("wifi.ssid", "ssid", ("ssid",), "wifi", "Nome da rede"),
    _f("wifi.ssid.enabled", "ssid", ("bool",), "wifi", "Rede ligada"),
    _f("wifi.ssid.radio", "ssid", ("ref", "radio"), "wifi", "Rádio da rede"),
    _f("wifi.security_mode", "ssid", ("enum", SECURITY), "wifi", "Segurança"),
    _f("wifi.password.set", "ssid", ("bool",), "wifi", "Senha definida"),
    _f("lan.ipv4_address", "lan", ("ipv4",), "lan", "Endereço IPv4 da LAN"),
    _f("lan.netmask", "lan", ("ipv4",), "lan", "Máscara"),
    _f("lan.dhcp_enabled", "lan", ("bool",), "lan", "Servidor DHCP"),
    _f("lan.dhcp_min", "lan", ("ipv4",), "lan", "Início da faixa DHCP"),
    _f("lan.dhcp_max", "lan", ("ipv4",), "lan", "Fim da faixa DHCP"),
    _f("lan.dns", "lan", ("dns",), "lan", "DNS entregues por DHCP"),
    _f("wan.type", "wan", ("enum", ("ppp", "ip", "bridge")), "wan", "Tipo de conexão"),
    _f("wan.status", "wan", ("enum", _CONN), "wan", "Estado"),
    _f("wan.vlan_id", "wan", ("int", 0, 4094), "wan", "VLAN"),
    _f("wan.nat_enabled", "wan", ("bool",), "wan", "NAT"),
    _f("wan.ipv6_enabled", "wan", ("bool",), "wan", "IPv6"),
    _f("wan.pppoe.password.set", "wan", ("bool",), "wan", "Senha PPPoE definida"),
    _f("optical.rx_dbm", "optical", ("float", -60.0, 10.0), "optical", "Potência recebida", "dBm"),
    _f("optical.tx_dbm", "optical", ("float", -10.0, 10.0), "optical", "Potência transmitida", "dBm"),
])
INSTANCE_RE = re.compile(r"^(radio|ssid|lan|wan|optical)/[0-9]{1,3}$")
GROUPS = (("wifi", "Wi-Fi"), ("lan", "LAN"), ("wan", "WAN"), ("optical", "Óptica"))
READ_ONLY_GROUPS = frozenset({"optical"})


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check_value(spec: Field, v) -> bool:
    k = spec.kind
    if k[0] == "bool":
        return isinstance(v, bool)
    if k[0] == "enum":
        return isinstance(v, str) and v in k[1]
    if k[0] == "int":
        return _is_int(v) and k[1] <= v <= k[2]
    if k[0] == "float":
        return isinstance(v, (int, float)) and not isinstance(v, bool) and k[1] <= float(v) <= k[2] and v == v
    if k[0] == "ssid":
        return isinstance(v, str) and bool(_SSID.match(v)) and len(v.encode()) <= 32
    if k[0] == "ref":
        return isinstance(v, str) and bool(re.fullmatch(rf"{k[1]}/[0-9]{{1,3}}", v))
    if k[0] in ("ipv4", "dns"):
        if not isinstance(v, str) or (k[0] == "dns" and not _DNS.match(v)):
            return False
        try:
            return all(isinstance(ipaddress.ip_address(x), ipaddress.IPv4Address) for x in v.split(","))
        except ValueError:
            return False
    return False


def check_field(name: str, instance: str, value) -> str | None:
    """None when valid, else a stable code."""
    spec = FIELDS.get(name)
    if spec is None:
        return "unknown_field"
    if not INSTANCE_RE.match(instance) or instance.split("/")[0] != spec.scope:
        return "instance_not_valid_for_field"
    if not check_value(spec, value):
        return "value_not_valid_for_field"
    return None


# ---- capabilities: semantic ids, derived from what was observed; `op` links a write to the job-engine operation the Capability Registry already knows
@dataclass(frozen=True)
class Capability:
    id: str
    group: str
    reads: tuple[str, ...]   # fields whose observation makes the READ supported
    write: bool
    risk: str                # R0..R3 (RISK_MATRIX_AND_GATES default scale)
    op: str | None = None    # registry operation (device_capabilities) this write maps to
    unit: str | None = None


CAPABILITIES: tuple[Capability, ...] = (
    Capability("wifi.ssid.read", "wifi", ("wifi.ssid",), False, "R0"),
    Capability("wifi.ssid.write", "wifi", ("wifi.ssid",), True, "R1", "set_wifi_ssid"),
    Capability("wifi.enabled.read", "wifi", ("wifi.ssid.enabled", "wifi.radio.enabled"), False, "R0"),
    Capability("wifi.enabled.write", "wifi", ("wifi.ssid.enabled", "wifi.radio.enabled"), True, "R1"),
    Capability("wifi.password.write", "wifi", ("wifi.password.set",), True, "R2"),
    Capability("wifi.security_mode.read", "wifi", ("wifi.security_mode",), False, "R0"),
    Capability("wifi.channel.read", "wifi", ("wifi.channel", "wifi.channel_auto"), False, "R0"),
    Capability("wifi.channel.write", "wifi", ("wifi.channel", "wifi.channel_auto"), True, "R2"),
    Capability("wifi.channel_width.read", "wifi", ("wifi.channel_width",), False, "R0"),
    Capability("wifi.channel_width.write", "wifi", ("wifi.channel_width",), True, "R2"),
    Capability("wifi.transmit_power.read", "wifi", ("wifi.transmit_power",), False, "R0"),
    Capability("wifi.transmit_power.write", "wifi", ("wifi.transmit_power",), True, "R2"),
    Capability("lan.ipv4.read", "lan", ("lan.ipv4_address", "lan.netmask"), False, "R0"),
    Capability("lan.ipv4.write", "lan", ("lan.ipv4_address", "lan.netmask"), True, "R3"),
    Capability("lan.dhcp.read", "lan", ("lan.dhcp_enabled", "lan.dhcp_min", "lan.dhcp_max", "lan.dns"), False, "R0"),
    Capability("lan.dhcp.write", "lan", ("lan.dhcp_enabled", "lan.dhcp_min", "lan.dhcp_max", "lan.dns"), True, "R3"),
    Capability("wan.connection.read", "wan", ("wan.type", "wan.status", "wan.vlan_id", "wan.nat_enabled", "wan.ipv6_enabled"), False, "R0"),
    Capability("wan.connection.write", "wan", ("wan.type", "wan.vlan_id", "wan.nat_enabled", "wan.ipv6_enabled", "wan.pppoe.password.set"), True, "R3"),
    Capability("optical.rx_dbm.read", "optical", ("optical.rx_dbm",), False, "R0", unit="dBm"),
    Capability("optical.tx_dbm.read", "optical", ("optical.tx_dbm",), False, "R0", unit="dBm"),
)
WRITES_ENABLED = False   # FC24-03/04: preview, approval and homologation come first. The reason is reported with every capability.
WRITE_BLOCK_REASON = "writes_not_enabled"


def revision(rows: list[dict]) -> str:
    """Stable fingerprint of the observed configuration (for the future If-Match of a change): changes only when a name, instance or value changes."""
    blob = "\n".join(f"{r['name']}|{r['instance_key']}|{json.dumps(r['value'], sort_keys=True)}" for r in sorted(rows, key=lambda x: (x["name"], x["instance_key"])))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def quality(captured_at: datetime, now: datetime) -> str:
    return "fresh" if now - captured_at <= FRESH_FOR else "stale"


def overall_state(rows: list[dict], now: datetime) -> str:
    """no_data (nothing observed) | stale (nothing newer than 24 h: the source is silent) | partial_stale | fresh"""
    if not rows:
        return "no_data"
    newest = max(r["captured_at"] for r in rows)
    if now - newest > STALE_ALL_AFTER:
        return "stale"
    return "fresh" if all(quality(r["captured_at"], now) == "fresh" for r in rows) else "partial_stale"


def instances_of(rows: list[dict]) -> dict[str, list[dict]]:
    """Real instances with the band/radio binding the device itself reported. An SSID's band is its RADIO's band; if the radio or the band was not reported the
    label says so instead of guessing from the number ('ssid/3' is not '5 GHz' by position)."""
    by = {(r["name"], r["instance_key"]): r["value"] for r in rows}
    band_of = {r["instance_key"]: r["value"] for r in rows if r["name"] == "wifi.radio.band"}
    out: dict[str, list[dict]] = {"radio": [], "ssid": [], "lan": [], "wan": [], "optical": []}
    for key in sorted({r["instance_key"] for r in rows}, key=lambda k: (k.split("/")[0], int(k.split("/")[1]))):
        scope = key.split("/")[0]
        item: dict = {"key": key}
        if scope == "radio":
            b = band_of.get(key)
            item["label"] = f"Rádio {b.replace('GHz', ' GHz')}" if b else f"Rádio {key.split('/')[1]} (banda não informada)"
        elif scope == "ssid":
            rb = by.get(("wifi.ssid.radio", key))
            item["radio_binding"] = rb
            b = band_of.get(rb) if rb else None
            item["label"] = f"Rede {b.replace('GHz', ' GHz')}" if b else f"Rede {key.split('/')[1]} (banda não informada)"
        else:
            item["label"] = {"lan": "LAN", "wan": "WAN", "optical": "Óptica"}[scope] + f" {key.split('/')[1]}"
        out[scope].append(item)
    return out


def build_capabilities(rows: list[dict], fingerprint: dict, protocol: str | None, registry: list[dict]) -> list[dict]:
    """One entry per catalog capability. `support`: supported when the read side was observed, else unknown (never `unsupported`: absence of an observation is not a
    proof). `certification` follows the Capability Registry for the mapped job operation; `write_allowed` is false while writes are not enabled."""
    seen = {}
    for r in rows:
        seen.setdefault(r["name"], []).append(r["instance_key"])
    reg: dict[str, dict] = {}
    for e in registry:   # one entry per (operation, protocol): keep the one that says the most (supported + observed/certified wins over unknown)
        cur = reg.get(e["name"])
        if cur is None or (e["status"] == "supported" and e["certification"] in ("observed", "certified") and not (cur["status"] == "supported" and cur["certification"] in ("observed", "certified"))):
            reg[e["name"]] = e
    out = []
    for c in CAPABILITIES:
        keys = sorted({k for f in c.reads for k in seen.get(f, [])})
        entry = reg.get(c.op) if c.op else None
        if entry and entry["status"] == "supported" and entry["certification"] in ("observed", "certified"):
            cert = "certified_write"
        else:
            cert = "observed_read" if keys else "identified"
        inst_all = instances_of([r for r in rows if r["instance_key"] in keys])
        scope_items = [i for lst in inst_all.values() for i in lst]
        out.append({
            "capability": c.id, "group": c.group, "device_fingerprint": fingerprint, "protocol": protocol or "unknown",
            "support": "supported" if keys else "unknown", "certification": cert, "instances": scope_items, "risk": c.risk,
            "write_allowed": bool(c.write and WRITES_ENABLED and cert == "certified_write"),
            "write_blocked_reason": (WRITE_BLOCK_REASON if c.write else "read_only"),
            "unit": c.unit, "evidence_ref": entry["evidence_ref"] if entry else None,
        })
    return out


def build_form_schema(rows: list[dict], now: datetime, caps: list[dict]) -> dict:
    """Groups and fields for the sidebar: ONLY what was observed. Every field is read-only now, with the reason; secrets show 'set / not set', never a value; optical
    power is read-only for good. Instances are the device's real ones (the picker uses them)."""
    inst = instances_of(rows)
    label_of = {i["key"]: i["label"] for lst in inst.values() for i in lst}
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        by_name.setdefault(r["name"], []).append(r)
    caps_by_group: dict[str, list[dict]] = {}
    for c in caps:
        caps_by_group.setdefault(c["group"], []).append(c)
    groups = []
    for gid, title in GROUPS:
        fields = []
        for name, spec in FIELDS.items():
            if spec.group != gid:
                continue
            for r in sorted(by_name.get(name, []), key=lambda x: x["instance_key"]):
                secret = name.endswith(".password.set")
                if gid in READ_ONLY_GROUPS:
                    reason = "Somente leitura: a potência óptica é uma medição, não um ajuste."
                elif secret:
                    reason = "A senha só poderá ser definida (nunca lida) quando a alteração for liberada para este modelo."
                else:
                    reason = "Edição ainda não liberada: falta pré-visualização, aprovação e homologação deste modelo e firmware."
                fields.append({
                    "name": name, "instance_key": r["instance_key"], "instance_label": label_of.get(r["instance_key"]), "label": spec.label,
                    "input_type": "readonly", "editable": False, "disabled_reason": reason, "unit": spec.unit,
                    "value": ("definida" if r["value"] else "não definida") if secret else r["value"], "secret": secret,
                    "source": r["source"], "quality": quality(r["captured_at"], now), "captured_at": r["captured_at"].isoformat(),
                })
        if fields:
            groups.append({"id": gid, "title": title, "read_only": gid in READ_ONLY_GROUPS, "fields": fields,
                           "capabilities": [c["capability"] for c in caps_by_group.get(gid, []) if c["support"] == "supported"]})
    return {"state": overall_state(rows, now), "groups": groups, "instances": inst, "editable": False}
