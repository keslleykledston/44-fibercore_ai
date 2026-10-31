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


def _lan_error(params: dict) -> str | None:
    """LAN: máscara contígua, endereço de host (nem rede nem broadcast); faixa DHCP ordenada. Só coerência numérica: topologia real é da homologação."""
    a, m = params.get("lan.ipv4_address"), params.get("lan.netmask")
    if a is not None and m is not None:
        try:
            net = ipaddress.ip_network(f"{a}/{m}", strict=False)
        except ValueError:
            return "netmask_not_contiguous"
        ip = ipaddress.ip_address(a)
        if net.prefixlen > 30 or ip in (net.network_address, net.broadcast_address):
            return "address_not_a_host"
    lo, hi = params.get("lan.dhcp_min"), params.get("lan.dhcp_max")
    if lo is not None and hi is not None and ipaddress.ip_address(lo) > ipaddress.ip_address(hi):
        return "dhcp_range_inverted"
    return None


def validate(capability: str, instance: str, params: dict) -> str | None:
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
    return _lan_error(params) if capability.startswith("lan.") else None


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


__all__ = ["APPROVALS", "PREVIEW_TTL", "WRITE_FIELDS", "blockers", "build_diff", "expiry", "high_risk", "intent_hash", "observed", "validate"]
