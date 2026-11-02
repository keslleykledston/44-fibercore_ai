"""Discovery of ONUs that are NOT registered on an OLT yet (v2.5, FC25-01/02/03, ADR-0040): the pure decisions, no I/O.

An observation says "this serial was seen waiting for authorisation on this OLT/PON". Only `source == 'edge_read'` (the Edge reading the OLT) is AUTHORITATIVE;
a fixture or a manual import is shown but never counts as the OLT's word. Nothing here authorises anything: the queue is read-only evidence and the answer to
"can this ONU be authorised?" is always "not in this version".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

FRESH_FOR = timedelta(hours=1)    # the autofind list is the OLT's CURRENT state: an observation older than this is `stale` (never shown as "offline")
NEW_FOR = timedelta(hours=24)     # first seen within this window = `new`
SERIAL_RE = re.compile(r"^[A-Za-z0-9]{4,32}$")
PON_RE = re.compile(r"^[0-9]{1,3}(/[0-9]{1,3}){1,3}$")
SOURCES = ("fixture", "manual_import", "edge_read")
CONDITIONS = ("new", "waiting", "stale", "conflict")


@dataclass(frozen=True)
class Seen:
    olt_id: str
    pon_path: str
    serial: str
    first_seen_at: datetime
    last_seen_at: datetime
    source: str


def authoritative(source: str) -> bool:
    return source == "edge_read"


def condition(o: Seen, *, now: datetime, registered_serials: frozenset[str], places: dict[str, frozenset[tuple[str, str]]]) -> tuple[str, list[str]]:
    """The queue condition and WHY (stable codes). `conflict` wins: an identity that is not certain blocks everything else. Conflicts: the serial is already a
    registered ONU of this tenant, or the same serial was seen at another OLT/PON (a physical ONU is in one place: one of the two is wrong or it moved)."""
    why: list[str] = []
    serial = o.serial.upper()
    if serial in registered_serials:
        why.append("already_registered")
    if len(places.get(serial, frozenset()) - {(o.olt_id, o.pon_path)}) > 0:
        why.append("seen_elsewhere")
    if why:
        return "conflict", why
    if now - o.last_seen_at > FRESH_FOR:
        return "stale", ["not_seen_recently"]
    if now - o.first_seen_at <= NEW_FOR:
        return "new", []
    return "waiting", []
