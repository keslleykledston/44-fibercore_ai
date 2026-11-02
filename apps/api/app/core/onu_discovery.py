"""Discovery of ONUs that are NOT registered on an OLT yet (v2.5, FC25-01/02/03, ADR-0040): the pure decisions, no I/O.

An observation says "this serial was seen waiting for authorisation on this OLT/PON". Only `source == 'edge_read'` (the Edge reading the OLT) is AUTHORITATIVE;
a fixture or a manual import is shown but never counts as the OLT's word. Nothing here authorises anything: the queue is read-only evidence and the answer to
"can this ONU be authorised?" is always "not in this version".
"""
from __future__ import annotations

import re
from datetime import timedelta

FRESH_FOR = timedelta(hours=1)    # the autofind list is the OLT's CURRENT state: an observation older than this is `stale` (never shown as "offline")
NEW_FOR = timedelta(hours=24)     # first seen within this window = `new`
SERIAL_RE = re.compile(r"^[A-Za-z0-9]{4,32}$")
PON_RE = re.compile(r"^[0-9]{1,3}(/[0-9]{1,3}){1,3}$")
SOURCES = ("fixture", "manual_import", "edge_read")
CONDITIONS = ("new", "waiting", "stale", "conflict")


def authoritative(source: str) -> bool:
    return source == "edge_read"


def reasons(cond: str, *, already_registered: bool, seen_elsewhere: bool) -> list[str]:
    """Stable reason codes for a condition the database decided (see the CASE in `app.api.onu_discovery`): `conflict` wins over `stale`, `stale` over `new`/`waiting`.
    Conflicts: the serial is already a registered ONU of this tenant, or the same serial was seen at another OLT/PON (a physical ONU is in one place: one of the two is
    wrong or it moved)."""
    if cond == "conflict":
        return (["already_registered"] if already_registered else []) + (["seen_elsewhere"] if seen_elsewhere else [])
    return ["not_seen_recently"] if cond == "stale" else []
