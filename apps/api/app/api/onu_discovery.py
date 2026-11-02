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


SYNC_MAX_AGE = od.FRESH_FOR   # the autofind list is the OLT's CURRENT state: a read older than the freshness window is not turned into sightings, ask the OLT again


@router.post("/v1/olts/{olt_id}/onus/unregistered/sync")
def sync_from_read(olt_id: UUID, p: Principal = Depends(require("discovery:import")), conn: Connection = TENANT_CONN) -> dict:
    """Turn the Edge's last typed read of the OLT's autofind list (`olt.autofind`, already checked against its closed shape by the job that brought it) into `edge_read`
    sightings: the only authoritative source. Idempotent per read: the sighting is stamped with the QUESTION's time (`asked_at`, the Cloud's own job clock), and a read that is
    not newer than what a sighting already says changes nothing. A serial that an earlier read listed and this one does not is NOT touched (that is not proof it was
    authorised or removed): it simply ages into `stale`. Nothing is asked of the equipment here and nothing is authorised."""
    from app.core import olt_cache, olt_query
    _flag(conn, p)
    _olt(conn, olt_id)
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"discovery-sync:{olt_id}"})   # one sync at a time per OLT
    got = olt_cache.latest(conn, olt_id, "olt.autofind", "")
    if got is None:
        raise HTTPException(409, "no_read: ask the OLT for its autofind list first (query olt.autofind)")
    if got.get("source") != "job":
        raise HTTPException(409, "read_not_from_the_equipment")
    now = datetime.now(UTC)
    asked = datetime.fromisoformat(got["asked_at"])
    if asked > now + MAX_FUTURE_SKEW:   # the question's time comes from the Cloud's own clock: a future one is a defect, never a "fresh" read
        raise HTTPException(409, "read_in_the_future")
    if now - asked > SYNC_MAX_AGE:
        raise HTTPException(409, "read_too_old: ask the OLT again")
    if not olt_query.check_result("olt.autofind", got["data"]):   # the cache is trusted only as far as its shape: checked again at the point of use
        raise HTTPException(409, "read_not_usable")
    created = updated = unchanged = 0
    for e in got["data"]["entries"]:
        r = conn.execute(
            text("INSERT INTO onu_discovery_observations (tenant_id, olt_id, pon_path, serial, vendor_hint, source, first_seen_at, last_seen_at, created_by) "
                 "VALUES (:t,:o,:pon,:s,:v,'edge_read',:at,:at,:by) "
                 "ON CONFLICT (tenant_id, olt_id, pon_path, serial, source) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at, seen_count = onu_discovery_observations.seen_count + 1, "
                 "vendor_hint = COALESCE(EXCLUDED.vendor_hint, onu_discovery_observations.vendor_hint) WHERE onu_discovery_observations.last_seen_at < EXCLUDED.last_seen_at "
                 "RETURNING (xmax = 0) AS inserted"),
            {"t": p.tenant_id, "o": olt_id, "pon": e["pon_path"], "s": e["serial"], "v": e["vendor"], "at": asked, "by": p.id}).first()
        if r is None:
            unchanged += 1
        elif r.inserted:
            created += 1
        else:
            updated += 1
    audit(conn, p, "discovery.observations.synced", "olt", str(olt_id), {"source": "edge_read", "created": created, "updated": updated, "unchanged": unchanged})
    return {"olt_id": str(olt_id), "source": "edge_read", "created": created, "updated": updated, "unchanged": unchanged, "entries": len(got["data"]["entries"]),
            "asked_at": asked.isoformat(), "age_seconds": int((now - asked).total_seconds())}


# The condition is decided IN SQL (one place), per row, with indexed EXISTS lookups: the filter, the total and the page are all computed by the database, so a page can
# never hide a match and no request materialises the tenant's whole history. `conflict` wins (an uncertain identity blocks everything else), then `stale`, `new`, `waiting`.
_QUEUE_SQL = """
WITH d AS (
  SELECT DISTINCT ON (d.olt_id, d.pon_path, d.serial) d.id, d.tenant_id, d.olt_id, o.name AS olt_name, d.pon_path, d.serial, d.vendor_hint, d.source, d.first_seen_at, d.last_seen_at,
         d.seen_count
  FROM onu_discovery_observations d JOIN olts o ON o.tenant_id = d.tenant_id AND o.id = d.olt_id
  WHERE (CAST(:o AS uuid) IS NULL OR d.olt_id = CAST(:o AS uuid))
  ORDER BY d.olt_id, d.pon_path, d.serial, (d.source = 'edge_read') DESC, d.last_seen_at DESC
), c AS (
  SELECT d.*,
         EXISTS (SELECT 1 FROM onus r WHERE upper(r.serial) = d.serial) AS already_registered,
         EXISTS (SELECT 1 FROM onu_discovery_observations x WHERE x.tenant_id = d.tenant_id AND x.serial = d.serial AND (x.olt_id <> d.olt_id OR x.pon_path <> d.pon_path)) AS seen_elsewhere
  FROM d
), k AS (
  SELECT c.*, CASE WHEN already_registered OR seen_elsewhere THEN 'conflict' WHEN now() - last_seen_at > make_interval(secs => :fresh) THEN 'stale'
                   WHEN now() - first_seen_at <= make_interval(secs => :newfor) THEN 'new' ELSE 'waiting' END AS condition
  FROM c
)
SELECT k.*, count(*) OVER () AS total FROM k WHERE (CAST(:cond AS text) IS NULL OR condition = CAST(:cond AS text))
ORDER BY olt_name, olt_id, pon_path, serial LIMIT :lim OFFSET :off
"""


def _queue(conn: Connection, olt_id: UUID | None, cond: str | None, limit: int, offset: int) -> dict:
    rows = conn.execute(text(_QUEUE_SQL), {"o": olt_id, "cond": cond, "fresh": od.FRESH_FOR.total_seconds(), "newfor": od.NEW_FOR.total_seconds(), "lim": limit, "off": offset}).all()
    items = [{
        "id": str(r.id), "olt_id": str(r.olt_id), "olt_name": r.olt_name, "pon_path": r.pon_path, "serial": r.serial, "vendor_hint": r.vendor_hint, "source": r.source,
        "authoritative": od.authoritative(r.source), "first_seen_at": r.first_seen_at.isoformat(), "last_seen_at": r.last_seen_at.isoformat(), "seen_count": r.seen_count,
        "condition": r.condition, "reasons": od.reasons(r.condition, already_registered=r.already_registered, seen_elsewhere=r.seen_elsewhere),
        "erp_association": "unavailable", "customer": None, "authorization": "not_available",
    } for r in rows]
    if rows:
        total = rows[0].total
    elif offset == 0:
        total = 0
    else:   # a page past the end: the total still has to be right
        first = conn.execute(text(_QUEUE_SQL), {"o": olt_id, "cond": cond, "fresh": od.FRESH_FOR.total_seconds(), "newfor": od.NEW_FOR.total_seconds(), "lim": 1, "off": 0}).first()
        total = first.total if first else 0
    return {"items": items, "total": total, "offset": offset, "limit": limit, "truncated": offset + len(items) < total, "fresh_window_minutes": int(od.FRESH_FOR.total_seconds() // 60)}


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
