"""ONT Configuration Manager, mudanças (ADR-0036, FC24-03): política, validação e bloqueios da pré-visualização.

Nada aqui fala com equipamento. A pré-visualização responde "o que mudaria, com que risco, quem teria de aprovar e por que ainda não pode ir": o pedido nasce e morre
BLOQUEADO enquanto não houver (1) escrita habilitada, (2) capacidade certificada para este modelo e firmware, (3) dado fresco e (4) um executor. Tudo é lista fechada: uma
capacidade só aceita os campos canônicos dela, na instância que o aparelho informou, com o valor validado pelo mesmo catálogo da leitura."""
from __future__ import annotations

import hashlib
import ipaddress
import json
from datetime import datetime, timedelta

from app.core import ont_config

POLICY_VERSION = "2026-10-31.1"
PREVIEW_TTL = timedelta(minutes=15)
EXECUTOR_AVAILABLE = False   # FC24-04 (adaptador do Edge, só com autorização de laboratório). Enquanto falso, nada sai da nuvem.

# capacidade de escrita -> campos canônicos aceitos; `together`: todos obrigatórios no mesmo pedido
WRITE_FIELDS: dict[str, tuple[tuple[str, ...], bool]] = {
    "wifi.ssid.write": (("wifi.ssid",), True),
    "wifi.enabled.write": (("wifi.ssid.enabled", "wifi.radio.enabled"), False),
    "wifi.password.write": (("wifi.password.set",), True),   # o valor da senha NÃO entra: só "trocar" (verdadeiro)
    "wifi.channel.write": (("wifi.channel", "wifi.channel_auto"), False),
    "wifi.channel_width.write": (("wifi.channel_width",), True),
    "wifi.transmit_power.write": (("wifi.transmit_power",), True),
    "lan.ipv4.write": (("lan.ipv4_address", "lan.netmask"), True),
    "lan.dhcp.write": (("lan.dhcp_enabled", "lan.dhcp_min", "lan.dhcp_max", "lan.dns"), False),
    "wan.connection.write": (("wan.type", "wan.vlan_id", "wan.nat_enabled", "wan.ipv6_enabled"), False),
}
# o canal de segredo (referência de segredo, nunca valor no pedido) ainda não existe
SECRET_CAPS = frozenset({"wifi.password.write"})
# regra do adendo v2.4: R1 uma aprovação que pode ser de quem pede; R2 uma aprovação de outra pessoa; R3 duas de outras pessoas + plano de recuperação
APPROVALS = {
    "R1": {"required": 1, "distinct_from_requester": False, "recovery_plan_required": False},
    "R2": {"required": 1, "distinct_from_requester": True, "recovery_plan_required": False},
    "R3": {"required": 2, "distinct_from_requester": True, "recovery_plan_required": True},
}
CAPS = {c.id: c for c in ont_config.CAPABILITIES if c.write}
assert set(WRITE_FIELDS) == set(CAPS), "every write capability needs its closed field list"


def high_risk(capability: str) -> bool:
    return CAPS[capability].risk == "R3"


def _net(addr, mask):
    try:
        return ipaddress.ip_network(f"{addr}/{mask}", strict=False)
    except ValueError:
        return None


def _effective(rows: list[dict], instance: str, params: dict, name: str):
    """What the device would have after the change: the request wins, else what was observed on this LAN instance."""
    return params[name] if name in params else current_value(rows, name, instance)[0]


def _range_problem(net, gw: str, lo: str, hi: str) -> str | None:
    """The DHCP range [lo, hi] against a subnet and its gateway: inside the subnet, clear of network and broadcast, not covering the gateway."""
    g, a, b = (int(ipaddress.ip_address(x)) for x in (gw, lo, hi))
    if any(ipaddress.ip_address(x) not in net or ipaddress.ip_address(x) in (net.network_address, net.broadcast_address) or ipaddress.ip_address(x) == ipaddress.ip_address(gw)
           for x in (lo, hi)):
        return "dhcp_range_outside_subnet"
    if a <= g <= b or int(net.network_address) in range(a, b + 1) or int(net.broadcast_address) in range(a, b + 1):
        return "dhcp_range_contains_gateway" if a <= g <= b else "dhcp_range_outside_subnet"
    return None


def _lan_error(rows: list[dict], instance: str, params: dict) -> str | None:
    """LAN: contiguous mask, a host address (neither network nor broadcast); DHCP range ordered, inside the subnet and clear of network, broadcast and the gateway itself.
    Pure numeric coherence: the real topology is the homologation's business."""
    a, m = params.get("lan.ipv4_address"), params.get("lan.netmask")
    if a is not None and m is not None:
        net = _net(a, m)
        if net is None:
            return "netmask_not_contiguous"
        ip = ipaddress.ip_address(a)
        if net.prefixlen > 30 or ip in (net.network_address, net.broadcast_address):
            return "address_not_a_host"
    lo, hi = params.get("lan.dhcp_min"), params.get("lan.dhcp_max")
    if lo is not None and hi is not None and ipaddress.ip_address(lo) > ipaddress.ip_address(hi):
        return "dhcp_range_inverted"
    if "lan.dhcp_min" in params or "lan.dhcp_max" in params:
        lo, hi = _effective(rows, instance, params, "lan.dhcp_min"), _effective(rows, instance, params, "lan.dhcp_max")
        gw, mask = _effective(rows, instance, params, "lan.ipv4_address"), _effective(rows, instance, params, "lan.netmask")
        net = _net(gw, mask) if gw and mask else None
        if not (lo and hi):
            return "dhcp_range_incomplete"   # changing one end needs the other end known (observed or in the request)
        if ipaddress.ip_address(lo) > ipaddress.ip_address(hi):
            return "dhcp_range_inverted"
        if net is None:
            return "lan_address_not_observed"   # cannot prove the range fits a subnet nobody reported
        return _range_problem(net, gw, lo, hi)
    return None


def warnings_for(rows: list[dict], capability: str, instance: str, params: dict) -> list[str]:
    """Not refusals: facts the operator must see. A new LAN subnet that leaves the CURRENT DHCP range outside it would strand the clients."""
    if capability != "lan.ipv4.write":
        return []
    gw, mask = params["lan.ipv4_address"], params["lan.netmask"]
    net = _net(gw, mask)
    lo, hi = current_value(rows, "lan.dhcp_min", instance)[0], current_value(rows, "lan.dhcp_max", instance)[0]
    if net is not None and lo and hi and _range_problem(net, gw, lo, hi):
        return ["dhcp_range_outside_new_subnet"]
    return []


def validate(capability: str, instance: str, params: dict, rows: list[dict]) -> str | None:
    """None when the request is well formed, else a stable code."""
    if capability not in WRITE_FIELDS:
        return "unknown_capability"
    names, together = WRITE_FIELDS[capability]
    if not params or any(k not in names for k in params):
        return "field_not_allowed_for_capability"
    if together and set(params) != set(names):
        return "fields_must_come_together"
    for k, v in params.items():
        code = ont_config.check_field(k, instance, v)
        if code:
            return code
        if k.endswith(".password.set") and v is not True:
            return "password_value_not_accepted"
    if capability == "wifi.enabled.write" and len(params) != 1:
        return "one_field_per_request"
    return _lan_error(rows, instance, params) if capability.startswith("lan.") else None


def current_value(rows: list[dict], name: str, instance: str):
    for r in rows:
        if r["name"] == name and r["instance_key"] == instance:
            return r["value"], True
    return None, False


def observed(rows: list[dict], capability: str, instance: str) -> bool:
    """The instance must be one the device itself reported for this capability (never a guess from a number)."""
    reads = CAPS[capability].reads
    return any(r["instance_key"] == instance and r["name"] in reads for r in rows)


def build_diff(rows: list[dict], capability: str, instance: str, params: dict) -> list[dict]:
    out = []
    for k, v in sorted(params.items()):
        cur, known = current_value(rows, k, instance)
        spec = ont_config.FIELDS[k]
        if k.endswith(".password.set"):
            out.append({"field": k, "label": spec.label, "from": ("definida" if cur else "não definida") if known else None, "to": "nova senha (valor não exibido)",
                        "secret": True, "changes": True})
        else:
            out.append({"field": k, "label": spec.label, "from": cur if known else None, "to": v, "secret": False, "changes": (not known) or cur != v})
    return out


def intent_hash(tenant_id, cpe_id, capability: str, instance: str, params: dict, base_revision: str) -> str:
    blob = json.dumps({"tenant": str(tenant_id), "cpe": str(cpe_id), "capability": capability, "instance": instance, "params": params, "base_revision": base_revision,
                       "policy": POLICY_VERSION, "form_schema": "2.4"}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def blockers(capability: str, instance: str, rows: list[dict], caps: list[dict], base_revision: str, now: datetime) -> list[str]:
    """Why this cannot go yet, in a fixed order; empty only when everything is ready (it is never, today: the executor does not exist)."""
    out = []
    if not ont_config.WRITES_ENABLED:
        out.append("writes_not_enabled")
    cap = next((c for c in caps if c["capability"] == capability), None)
    if cap is None or cap["support"] != "supported":
        out.append("capability_not_supported")
    if cap is None or cap["certification"] != "certified_write":
        out.append("capability_not_certified")
    if ont_config.revision(rows) != base_revision:
        out.append("stale_revision")
    reads = CAPS[capability].reads
    inst_rows = [r for r in rows if r["instance_key"] == instance and r["name"] in reads]
    if ont_config.overall_state(rows, now) != "fresh" or any(ont_config.quality(r["captured_at"], now) != "fresh" for r in inst_rows):
        out.append("stale_data")
    if capability in SECRET_CAPS:
        out.append("secret_channel_not_available")
    if any(r["source"] == "mock" for r in rows):
        out.append("synthetic_source")
    if not EXECUTOR_AVAILABLE:
        out.append("executor_not_available")
    return out


def expiry(now: datetime) -> datetime:
    return now + PREVIEW_TTL


__all__ = ["APPROVALS", "PREVIEW_TTL", "WRITE_FIELDS", "blockers", "build_diff", "expiry", "high_risk", "intent_hash", "observed", "validate", "warnings_for"]
