"""ONU discovery queue API (v2.5, FC25-01/02/03, ADR-0040): serials waiting for authorisation, READ-ONLY.

Observations come from three sources and only `edge_read` (the Edge reading the OLT, a later supervised delivery) is authoritative; a fixture or a manual import is stored and shown
as such but never refreshes or replaces what the OLT said. Nothing here authorises an ONU, opens a job or touches equipment. The ERP association is reported as `unavailable`
because no ERP serial source exists for unregistered ONUs yet (it is never guessed). The whole router answers 403 `feature_disabled` while the tenant flag `onu_discovery` is off.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import features
from app.core import onu_discovery as od

router = APIRouter()

MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_ITEMS = 200
LIST_LIMIT = 200      # default page size (max 500)
SCAN_CAP = 20_000     # most de-duplicated sightings examined per request; beyond it the answer says so (`scan_capped`)


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "onu_discovery")


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pon_path: str = Field(pattern=r"^[0-9]{1,3}(/[0-9]{1,3}){1,3}$")
    serial: str = Field(pattern=r"^[A-Za-z0-9]{4,32}$")
    vendor_hint: str | None = Field(None, min_length=1, max_length=40)
    observed_at: datetime


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["fixture", "manual_import"] = "manual_import"   # `edge_read` is reserved for the Edge reader (a later, supervised delivery)
    items: list[Item] = Field(min_length=1, max_length=MAX_ITEMS)


def _olt(conn: Connection, olt_id: UUID):
    r = conn.execute(text("SELECT id, name FROM olts WHERE id = :i"), {"i": olt_id}).first()   # RLS: another tenant's OLT is simply not found
    if r is None:
        raise HTTPException(404, "olt not found")
    return r


@router.post("/v1/olts/{olt_id}/onus/unregistered/import", status_code=201)
def import_observations(olt_id: UUID, body: ImportIn, p: Principal = Depends(require("discovery:import")), conn: Connection = TENANT_CONN) -> dict:
    """Record sightings (idempotent per OLT/PON/serial/source: a repeat moves `last_seen_at` forward and counts). Nothing reaches the OLT."""
    _flag(conn, p)
    _olt(conn, olt_id)
    now = datetime.now(UTC)
    created = updated = 0
    seen_keys: set[tuple[str, str]] = set()
    for it in body.items:
        if it.observed_at.tzinfo is None:
            raise HTTPException(422, "observed_at must be timezone-aware")
        if it.observed_at > now + MAX_FUTURE_SKEW:
            raise HTTPException(422, "observed_at is in the future")
        key = (it.pon_path, it.serial.upper())
        if key in seen_keys:
            raise HTTPException(422, "duplicate serial/PON in the request")
        seen_keys.add(key)
    for it in body.items:
        r = conn.execute(
            text("INSERT INTO onu_discovery_observations (tenant_id, olt_id, pon_path, serial, vendor_hint, source, first_seen_at, last_seen_at, created_by) "
                 "VALUES (:t,:o,:pon,:s,:v,:src,:at,:at,:by) "
                 "ON CONFLICT (tenant_id, olt_id, pon_path, serial, source) DO UPDATE SET last_seen_at = GREATEST(onu_discovery_observations.last_seen_at, EXCLUDED.last_seen_at), "
                 "seen_count = onu_discovery_observations.seen_count + 1, vendor_hint = COALESCE(EXCLUDED.vendor_hint, onu_discovery_observations.vendor_hint) "
                 "RETURNING (xmax = 0) AS inserted"),
            {"t": p.tenant_id, "o": olt_id, "pon": it.pon_path, "s": it.serial.upper(), "v": it.vendor_hint, "src": body.source, "at": it.observed_at, "by": p.id}).one()
        created += 1 if r.inserted else 0
        updated += 0 if r.inserted else 1
    audit(conn, p, "discovery.observations.imported", "olt", str(olt_id), {"source": body.source, "created": created, "updated": updated})
    return {"olt_id": str(olt_id), "source": body.source, "created": created, "updated": updated}


def _queue(conn: Connection, olt_id: UUID | None, cond: str | None, limit: int, offset: int) -> dict:
    now = datetime.now(UTC)
    rows = conn.execute(
        text("SELECT DISTINCT ON (d.olt_id, d.pon_path, d.serial) d.id, d.olt_id, o.name AS olt_name, d.pon_path, d.serial, d.vendor_hint, d.source, d.first_seen_at, d.last_seen_at, d.seen_count "
             "FROM onu_discovery_observations d JOIN olts o ON o.tenant_id = d.tenant_id AND o.id = d.olt_id "
             "WHERE (CAST(:o AS uuid) IS NULL OR d.olt_id = CAST(:o AS uuid)) "
             "ORDER BY d.olt_id, d.pon_path, d.serial, (d.source = 'edge_read') DESC, d.last_seen_at DESC LIMIT :lim"),
        {"o": olt_id, "lim": SCAN_CAP}).all()
    registered = frozenset(r.serial.upper() for r in conn.execute(text("SELECT serial FROM onus")).all())
    places: dict[str, set[tuple[str, str]]] = {}
    for r in conn.execute(text("SELECT DISTINCT olt_id, pon_path, serial FROM onu_discovery_observations")).all():
        places.setdefault(r.serial.upper(), set()).add((str(r.olt_id), r.pon_path))
    frozen = {k: frozenset(v) for k, v in places.items()}
    items = []
    for r in rows:
        seen = od.Seen(str(r.olt_id), r.pon_path, r.serial, r.first_seen_at, r.last_seen_at, r.source)
        c, why = od.condition(seen, now=now, registered_serials=registered, places=frozen)
        if cond and c != cond:
            continue
        items.append({
            "id": str(r.id), "olt_id": str(r.olt_id), "olt_name": r.olt_name, "pon_path": r.pon_path, "serial": r.serial, "vendor_hint": r.vendor_hint, "source": r.source,
            "authoritative": od.authoritative(r.source), "first_seen_at": r.first_seen_at.isoformat(), "last_seen_at": r.last_seen_at.isoformat(), "seen_count": r.seen_count,
            "condition": c, "reasons": why, "erp_association": "unavailable", "customer": None, "authorization": "not_available",
        })
    page = items[offset:offset + limit]   # the condition filter is applied BEFORE paging, so a page never hides a match that sits later in the scan
    return {"items": page, "total": len(items), "offset": offset, "limit": limit, "truncated": offset + limit < len(items), "scan_capped": len(rows) >= SCAN_CAP,
            "fresh_window_minutes": int(od.FRESH_FOR.total_seconds() // 60)}


@router.get("/v1/olts/{olt_id}/onus/unregistered")
def list_for_olt(olt_id: UUID, condition: Literal["new", "waiting", "stale", "conflict"] | None = Query(None), limit: int = Query(LIST_LIMIT, ge=1, le=500),
                 offset: int = Query(0, ge=0, le=100_000), p: Principal = Depends(require("discovery:read")),
                 conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    _olt(conn, olt_id)
    return _queue(conn, olt_id, condition, limit, offset)


@router.get("/v1/discovery/onus")
def list_all(condition: Literal["new", "waiting", "stale", "conflict"] | None = Query(None), limit: int = Query(LIST_LIMIT, ge=1, le=500),
             offset: int = Query(0, ge=0, le=100_000), p: Principal = Depends(require("discovery:read")),
             conn: Connection = TENANT_CONN) -> dict:
    """The queue across all of this tenant's OLTs (RLS)."""
    _flag(conn, p)
    return _queue(conn, None, condition, limit, offset)
