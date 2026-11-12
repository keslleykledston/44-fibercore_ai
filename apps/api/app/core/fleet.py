"""Fleet Manager (ADR-0041, PR2): the pure rules of registering an OLT. No I/O.

D3 of the ADR (amended, migration 0048): the Cloud never holds, receives or echoes an OLT credential (login, password, SNMP community). The management ADDRESS is stored but only ever returned masked.
`credential_ref` is the NAME of a secret in the Edge's own local store; this module refuses anything
that is not shaped like a name (an address, a URL, a long hexadecimal string that looks like a key, spaces, upper case, separators other than `._-`).
"""
from __future__ import annotations

import ipaddress
import re

VENDORS = ("huawei", "datacom", "zte", "fiberhome", "intelbras", "vsol", "ubiquiti", "parks")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,58}[A-Za-z0-9]$")
POP_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,23}$")
CREDENTIAL_REF_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_IPV4 = re.compile(r"^[0-9]{1,3}(\.[0-9]{1,3}){3}$")
_KEYLIKE = re.compile(r"^[0-9a-f]{32,}$")


def credential_ref_problem(v: str) -> str | None:
    """None when `v` is acceptable as the name of a local secret; else a short reason (never echoing the value)."""
    if not CREDENTIAL_REF_RE.match(v):
        return "must be a name: lower-case letters, digits, '.', '_' or '-', up to 64 characters"
    if _IPV4.match(v):
        return "an address is not a credential name"
    if _KEYLIKE.match(v):
        return "looks like a key or hash, not a name"
    return None


SNMP_VERSIONS = ("v2c", "v3")


def address_problem(v: str) -> str | None:
    """None when `v` is a usable management IP literal (v4 or v6, no mask, no host name); else a short reason that never echoes the value."""
    try:
        ip = ipaddress.ip_address(v.strip())
    except ValueError:
        return "must be an IPv4 or IPv6 address (no host name, no port, no mask)"
    if ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_link_local:
        return "not a usable management address"
    return None


def mask_address(v: str | None) -> str | None:
    """What a reader may see of the address: IPv4 keeps the first two octets (`10.20.•.•`), IPv6 the first group. Enough to recognise it, not enough to use it."""
    if not v:
        return None
    ip = ipaddress.ip_address(v)
    if ip.version == 4:
        a = str(ip).split(".")
        return f"{a[0]}.{a[1]}.•.•"
    return ip.exploded.split(":")[0] + ":•:•:•:•:•:•:•"


def olt_name_problem(v: str) -> str | None:
    return None if NAME_RE.match(v) and ".." not in v and "  " not in v else "2 to 60 characters: letters, digits, space, '.', '_' or '-', no repeated separators"


# ---- ADR-0046 (migration 0051): how an OLT is reached. Telnet is INVENTORY only: nothing credential-bearing is ever accepted for it.
PROTOCOLS = ("ssh", "telnet")
DEFAULT_PORT = {"ssh": 22, "telnet": 23}
TRANSPORTS = ("cli", "snmp")
SSH_MODES = ("exec", "shell")
DEFAULT_SNMP_PORT = 161
HOST_KEY_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")   # what `ssh-keygen -lf` prints: SHA256: + the 43 base64 characters of the digest (no padding)
CONN_FIELDS = ("mgmt_protocol", "mgmt_port", "mgmt_transport", "snmp_port", "host_key_sha256", "ssh_mode", "legacy_ssh")


class ConnectionRuleError(ValueError):
    """A rule between the connection fields was broken; `.code` is the stable detail the API answers (422), never the value."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def merge_connection(cur: dict, sent: dict, snmp_version: str | None) -> dict:
    """The connection fields an OLT will have: what it has now (`cur`) overridden by what was sent, with the defaults of the protocol (ssh: 22, exec, cli; telnet: 23)
    and the cross-field rules of ADR-0046 D3.
    `sent` holds only the fields the caller sent (an explicit None clears). Raises ConnectionRuleError."""
    new = {**{k: cur.get(k) for k in CONN_FIELDS}, **{k: v for k, v in sent.items() if k in CONN_FIELDS}}
    new["legacy_ssh"] = bool(new.get("legacy_ssh"))
    proto = new["mgmt_protocol"]
    if proto is None:
        if any(sent.get(k) for k in ("mgmt_port", "host_key_sha256", "ssh_mode", "legacy_ssh")):
            raise ConnectionRuleError("protocol_required")   # a port, a fingerprint or an ssh option only make sense with a protocol
        new.update(mgmt_port=None, host_key_sha256=None, ssh_mode=None, legacy_ssh=False)
    else:
        changed = proto != cur.get("mgmt_protocol")
        if new["mgmt_port"] is None or (changed and "mgmt_port" not in sent):
            new["mgmt_port"] = DEFAULT_PORT[proto]   # 22 for ssh, 23 for telnet; a port typed together with the change wins
        if proto == "telnet":
            if sent.get("host_key_sha256") is not None or sent.get("ssh_mode") is not None or sent.get("legacy_ssh"):
                raise ConnectionRuleError("telnet_has_no_ssh_fields")
            new.update(host_key_sha256=None, ssh_mode=None, legacy_ssh=False)   # what a switch ssh -> telnet leaves behind is dropped: it no longer means anything
        else:
            new["ssh_mode"] = new["ssh_mode"] or "exec"
            new["mgmt_transport"] = new["mgmt_transport"] or "cli"
    if new["mgmt_transport"] == "snmp":
        if snmp_version != "v2c":
            raise ConnectionRuleError("snmp_transport_needs_v2c")
        new["snmp_port"] = new["snmp_port"] or DEFAULT_SNMP_PORT
    return new


STAGES = ("registered", "telnet_inventory", "connection_applied", "awaiting_trust", "trusted", "credential_applied", "tested")


def readiness(*, protocol: str | None, transport: str | None, conn_applied: bool, trust: str, ssh_cred: bool, snmp_cred: bool, tested: bool) -> dict:
    """Where the OLT is on the way to being usable (ADR-0046 D3): registered -> connection applied at the Edge -> (awaiting local confirmation at the Edge) -> trusted -> credential applied -> tested.
    `managed` is False for an OLT that never said how it is reached (the older registrations: the Edge's own configuration is the truth there)."""
    if protocol is None:
        return {"managed": False, "stage": "registered", "steps": {"connection": False, "trust": "none", "credential": False, "tested": False}}
    if protocol == "telnet":
        return {"managed": True, "stage": "telnet_inventory", "steps": {"connection": False, "trust": "none", "credential": False, "tested": False}}
    cred = snmp_cred if transport == "snmp" else ssh_cred
    if not conn_applied:
        stage = "registered"
    elif trust == "awaiting_local_trust":
        stage = "awaiting_trust"
    elif trust != "trusted":
        stage = "connection_applied"
    elif not cred:
        stage = "trusted"
    else:
        stage = "tested" if tested else "credential_applied"
    return {"managed": True, "stage": stage, "steps": {"connection": conn_applied, "trust": trust, "credential": cred, "tested": tested}}
