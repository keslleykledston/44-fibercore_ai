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
