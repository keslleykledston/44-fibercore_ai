"""Fleet Manager (ADR-0041, PR2): the pure rules of registering an OLT. No I/O.

D3 of the ADR: the Cloud never holds, receives or echoes an OLT credential or address. `credential_ref` is the NAME of a secret in the Edge's own local store; this module refuses anything
that is not shaped like a name (an address, a URL, a long hexadecimal string that looks like a key, spaces, upper case, separators other than `._-`).
"""
from __future__ import annotations

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


def olt_name_problem(v: str) -> str | None:
    return None if NAME_RE.match(v) and ".." not in v and "  " not in v else "2 to 60 characters: letters, digits, space, '.', '_' or '-', no repeated separators"
