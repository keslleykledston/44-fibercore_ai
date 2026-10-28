"""Inventory ingestion (Edge -> Cloud) and read APIs. READ-ONLY toward the network: nothing here
sends anything to a device. Freshness is computed at read time so Edge/OLT silence shows as `stale`,
never as a fabricated ONU `offline`."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Connection, text

from app.api.deps import Principal, require, tenant_conn
from app.api.noc import evaluate_pons
from app.events import outbox

router = APIRouter()

FRESH_FOR = timedelta(minutes=15)
MAX_FUTURE_SKEW = timedelta(minutes=5)
LEVEL_ORDER = {"identified": 0, "observed": 1, "certified": 2}
Short = Annotated[str, Field(min_length=1, max_length=128)]


def _check_observed(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    if v > datetime.now(UTC) + MAX_FUTURE_SKEW:
        raise ValueError("observed_at is in the future")
    return v


class PonIn(BaseModel):
    pon_path: Short
    status: Literal["up", "down", "unknown"] = "unknown"
    # True only when this snapshot lists EVERY ONU of the PON (full port read). Incident correlation uses complete PONs
    # exclusively: a partial sample can neither open nor close a mass-outage incident.
    complete: bool = False


class OnuIn(BaseModel):
    serial: Short
    pon_path: Short | None = None
    status: Literal["online", "offline", "los", "dying_gasp", "unknown"] = "unknown"
    rx_dbm: float | None = Field(default=None, ge=-50, le=10)


class OltSnapshot(BaseModel):
    edge_id: UUID
    observed_at: datetime
    name: Short
    vendor: Short
    model: Short | None = None
    firmware: Short | None = None
    driver_level: Literal["identified", "observed"] = "identified"  # 'certified' is never self-declared
    pons: list[PonIn] = Field(default_factory=list, max_length=256)
    onus: list[OnuIn] = Field(default_factory=list, max_length=5000)

    _obs = field_validator("observed_at")(_check_observed)


class CpeBinding(BaseModel):
    protocol: Literal["tr069", "tr369"]
    external_id: Short
    connector_id: Short


class CpeIn(BaseModel):
    canonical_serial: Short
    vendor: Short | None = None
    model: Short | None = None
    firmware: Short | None = None
    binding: CpeBinding


class CpeSnapshot(BaseModel):
    edge_id: UUID
    observed_at: datetime
    cpes: list[CpeIn] = Field(max_length=5000)

    _obs = field_validator("observed_at")(_check_observed)


def _bound_edge(p: Principal, edge_id: UUID) -> None:
    if p.edge_id is None or p.edge_id != edge_id:
        raise HTTPException(403, "token is not bound to this edge")


@router.post("/v1/edge/olt-snapshots", status_code=202)
def ingest_olt_snapshot(
    body: OltSnapshot, p: Principal = Depends(require("inventory:write")), conn: Connection = Depends(tenant_conn)
) -> dict:
    _bound_edge(p, body.edge_id)
    row = conn.execute(
        text("SELECT id, edge_id, observed_at, support_level FROM olts WHERE name = :n FOR UPDATE"), {"n": body.name}
    ).first()
    if row and row.edge_id != body.edge_id:
        raise HTTPException(409, "olt name owned by another edge")  # an edge cannot hijack another's OLT
    if row and row.observed_at and body.observed_at < row.observed_at:
        return {"status": "ignored_stale", "olt_id": str(row.id)}  # out-of-order replay never overwrites newer data
    # Server-side cap: cloud never trusts a self-declared level above 'observed'; 'certified' needs homologation record.
    level = body.driver_level
    if row and row.support_level == "certified":
        level = "certified"
    if row:
        olt_id = row.id
        conn.execute(
            text("UPDATE olts SET vendor=:v, model=:m, firmware=:f, support_level=:l, observed_at=:o WHERE id=:i"),
            {"v": body.vendor, "m": body.model, "f": body.firmware, "l": level, "o": body.observed_at, "i": olt_id},
        )
    else:
        created = conn.execute(
            text(
                "INSERT INTO olts (tenant_id, edge_id, name, vendor, model, firmware, support_level, observed_at) "
                "VALUES (:t,:e,:n,:v,:m,:f,:l,:o) ON CONFLICT (tenant_id, name) DO NOTHING RETURNING id"
            ),
            {"t": p.tenant_id, "e": body.edge_id, "n": body.name, "v": body.vendor, "m": body.model,
             "f": body.firmware, "l": level, "o": body.observed_at},
        ).scalar_one_or_none()
        if created is None:  # lost a first-ingest race: another request created it; re-run the existing-OLT checks
            row = conn.execute(
                text("SELECT id, edge_id, observed_at FROM olts WHERE name = :n FOR UPDATE"), {"n": body.name}
            ).first()
            if row.edge_id != body.edge_id:
                raise HTTPException(409, "olt name owned by another edge")
            if row.observed_at and body.observed_at < row.observed_at:
                return {"status": "ignored_stale", "olt_id": str(row.id)}
            olt_id = row.id
            conn.execute(
                text("UPDATE olts SET vendor=:v, model=:m, firmware=:f, support_level=:l, observed_at=:o WHERE id=:i"),
                {"v": body.vendor, "m": body.model, "f": body.firmware, "l": level, "o": body.observed_at, "i": olt_id},
            )
        else:
            olt_id = created
    if body.pons:  # one round trip for all PONs, then one lookup of the OLT's PON map
        conn.execute(
            text(
                "INSERT INTO pon_ports (tenant_id, olt_id, pon_path, status, observed_at) VALUES (:t,:o,:p,:s,:ts) "
                "ON CONFLICT (tenant_id, olt_id, pon_path) DO UPDATE SET status=EXCLUDED.status, observed_at=EXCLUDED.observed_at "
                "WHERE pon_ports.observed_at IS NULL OR pon_ports.observed_at <= EXCLUDED.observed_at"
            ),
            [{"t": p.tenant_id, "o": olt_id, "p": x.pon_path, "s": x.status, "ts": body.observed_at} for x in body.pons],
        )
    pon_ids = {
        r.pon_path: r.id
        for r in conn.execute(text("SELECT id, pon_path FROM pon_ports WHERE tenant_id=:t AND olt_id=:o"), {"t": p.tenant_id, "o": olt_id})
    }
    if body.onus:
        conn.execute(
            text(
                "INSERT INTO onus (tenant_id, olt_id, pon_id, serial, status, rx_dbm, observed_at, last_online_at) "
                "VALUES (:t,:o,:pi,:s,:st,:rx,:ts, CASE WHEN CAST(:st AS text) = 'online' THEN CAST(:ts AS timestamptz) END) "
                "ON CONFLICT (tenant_id, olt_id, serial) DO UPDATE SET pon_id=EXCLUDED.pon_id, status=EXCLUDED.status, "
                "rx_dbm=EXCLUDED.rx_dbm, observed_at=EXCLUDED.observed_at, "
                "last_online_at = CASE WHEN EXCLUDED.status = 'online' THEN EXCLUDED.observed_at ELSE onus.last_online_at END, "
                # down_since only records a REAL transition (seen online, now seen down). An ONU first seen down, or coming from
                # 'unknown', has no known drop time and stays NULL: it is chronic as far as correlation can tell.
                "down_since = CASE WHEN EXCLUDED.status = 'online' THEN NULL "
                "WHEN onus.status = 'online' AND EXCLUDED.status IN ('offline','los','dying_gasp') THEN EXCLUDED.observed_at "
                "ELSE onus.down_since END "
                # STRICTLY newer: a snapshot with the same observed_at is a retry/replay of the one already applied and must not
                # re-apply states, or a reordered tie could fabricate or erase a drop (down_since is derived from the old row).
                "WHERE onus.observed_at IS NULL OR onus.observed_at < EXCLUDED.observed_at"
            ),
            [{"t": p.tenant_id, "o": olt_id, "pi": pon_ids.get(x.pon_path) if x.pon_path else None, "s": x.serial,
              "st": x.status, "rx": x.rx_dbm, "ts": body.observed_at} for x in body.onus],
        )
    evaluate_pons(conn, p.tenant_id, olt_id, [x.pon_path for x in body.pons if x.complete], [o.serial for o in body.onus],
                  body.observed_at)
    outbox.enqueue(
        conn, tenant_id=p.tenant_id, aggregate_type="olt", aggregate_id=olt_id, event_type="olt.snapshot_ingested",
        payload={"edge_id": str(body.edge_id), "pons": len(body.pons), "onus": len(body.onus),
                 "observed_at": body.observed_at.isoformat()},
    )
    return {"status": "accepted", "olt_id": str(olt_id), "pons": len(body.pons), "onus": len(body.onus)}


@router.post("/v1/edge/cpe-snapshots", status_code=202)
def ingest_cpe_snapshot(
    body: CpeSnapshot, p: Principal = Depends(require("inventory:write")), conn: Connection = Depends(tenant_conn)
) -> dict:
    _bound_edge(p, body.edge_id)
    all_serials = [c.canonical_serial for c in body.cpes]
    owners = {  # row locks serialise concurrent snapshots touching the same CPEs
        r.canonical_serial: (r.edge_id, r.observed_at)
        for r in conn.execute(
            text("SELECT edge_id, observed_at, canonical_serial FROM cpes WHERE tenant_id=:t AND canonical_serial = ANY(:s) FOR UPDATE"),
            {"t": p.tenant_id, "s": all_serials},
        )
    }
    if any(edge != body.edge_id for edge, _ in owners.values()):
        raise HTTPException(409, "cpe owned by another edge")  # an edge cannot overwrite another edge's CPEs
    # Out-of-order protection covers the WHOLE record: a CPE newer than this snapshot is skipped entirely,
    # bindings included, so a late replay cannot resurrect obsolete associations.
    fresh = [c for c in body.cpes if not (c.canonical_serial in owners and owners[c.canonical_serial][1]
                                          and owners[c.canonical_serial][1] > body.observed_at)]
    skipped = len(body.cpes) - len(fresh)
    if not fresh:
        return {"status": "ignored_stale", "cpes": 0, "skipped": skipped}
    serials = [c.canonical_serial for c in fresh]
    conn.execute(
        text(
            "INSERT INTO cpes (tenant_id, edge_id, canonical_serial, vendor, model, firmware, observed_at) "
            "VALUES (:t,:e,:s,:v,:m,:f,:o) ON CONFLICT (tenant_id, canonical_serial) DO UPDATE SET vendor=EXCLUDED.vendor, "
            "model=EXCLUDED.model, firmware=EXCLUDED.firmware, observed_at=EXCLUDED.observed_at "
            "WHERE cpes.edge_id = EXCLUDED.edge_id AND (cpes.observed_at IS NULL OR cpes.observed_at <= EXCLUDED.observed_at)"
        ),
        [{"t": p.tenant_id, "e": body.edge_id, "s": c.canonical_serial, "v": c.vendor, "m": c.model, "f": c.firmware,
          "o": body.observed_at} for c in fresh],
    )
    resolved = list(
        conn.execute(
            text("SELECT id, edge_id, canonical_serial FROM cpes WHERE tenant_id=:t AND canonical_serial = ANY(:s)"),
            {"t": p.tenant_id, "s": serials},
        )
    )
    # Re-check ownership AFTER the upsert: closes the race where two edges create the same new serial concurrently
    # (the loser's ON CONFLICT is a no-op; raising here rolls the whole request back, bindings included).
    if any(r.edge_id != body.edge_id for r in resolved):
        raise HTTPException(409, "cpe owned by another edge")
    ids = {r.canonical_serial: r.id for r in resolved}
    # A binding (connector, protocol, external_id) identifies ONE cpe; re-pointing it to another serial is refused.
    keys = [(c.binding.connector_id, c.binding.protocol, c.binding.external_id) for c in fresh]
    existing = {
        (r.connector_id, r.protocol, r.external_id): r.cpe_id
        for r in conn.execute(
            text("SELECT connector_id, protocol, external_id, cpe_id FROM cpe_protocol_bindings WHERE tenant_id=:t "
                 "AND external_id = ANY(:x)"),
            {"t": p.tenant_id, "x": [k[2] for k in keys]},
        )
    }
    for c, k in zip(fresh, keys, strict=True):
        if k in existing and existing[k] != ids[c.canonical_serial]:
            raise HTTPException(409, f"binding {k[2]} already linked to another cpe")
    conn.execute(
        text(
            "INSERT INTO cpe_protocol_bindings (tenant_id, cpe_id, protocol, external_id, connector_id, observed_at) "
            "VALUES (:t,:ci,:p,:x,:c,:o) ON CONFLICT (tenant_id, connector_id, protocol, external_id) "
            "DO UPDATE SET observed_at = GREATEST(cpe_protocol_bindings.observed_at, EXCLUDED.observed_at)"
        ),
        [{"t": p.tenant_id, "ci": ids[c.canonical_serial], "p": c.binding.protocol, "x": c.binding.external_id,
          "c": c.binding.connector_id, "o": body.observed_at} for c in fresh],
    )
    return {"status": "accepted", "cpes": len(fresh), "skipped": skipped}


# ---- reads ------------------------------------------------------------------------------------
def _fresh(ts: datetime | None) -> str:
    if ts is None:
        return "unknown"
    return "fresh" if datetime.now(UTC) - ts <= FRESH_FOR else "stale"


@router.get("/v1/olts")
def list_olts(
    limit: int = Query(100, ge=1, le=1000),
    p: Principal = Depends(require("inventory:read")),
    conn: Connection = Depends(tenant_conn),
) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT o.id, o.name, o.vendor, o.model, o.firmware, o.support_level, o.observed_at, o.edge_id, "
            "(SELECT count(*) FROM onus u WHERE u.tenant_id = o.tenant_id AND u.olt_id = o.id) AS onu_count "
            "FROM olts o ORDER BY o.name LIMIT :l"
        ),
        {"l": limit},
    )
    return [
        {"id": str(r.id), "name": r.name, "vendor": r.vendor, "model": r.model, "firmware": r.firmware,
         "support_level": r.support_level, "edge_id": str(r.edge_id), "onu_count": r.onu_count,
         "observed_at": r.observed_at.isoformat() if r.observed_at else None, "freshness": _fresh(r.observed_at)}
        for r in rows
    ]


@router.get("/v1/onus")
def list_onus(
    serial: str | None = Query(None, max_length=128),
    olt_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=1000),
    p: Principal = Depends(require("inventory:read")),
    conn: Connection = Depends(tenant_conn),
) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT u.id, u.olt_id, u.serial, u.status, u.rx_dbm, u.observed_at, pp.pon_path FROM onus u "
            "LEFT JOIN pon_ports pp ON pp.id = u.pon_id AND pp.tenant_id = u.tenant_id "
            "WHERE (CAST(:s AS text) IS NULL OR u.serial = :s) AND (CAST(:o AS uuid) IS NULL OR u.olt_id = :o) "
            "ORDER BY u.serial LIMIT :l"
        ),
        {"s": serial, "o": olt_id, "l": limit},
    )
    return [
        {"id": str(r.id), "olt_id": str(r.olt_id), "serial": r.serial, "pon_path": r.pon_path,
         "status": r.status, "rx_dbm": float(r.rx_dbm) if r.rx_dbm is not None else None,
         "observed_at": r.observed_at.isoformat() if r.observed_at else None, "freshness": _fresh(r.observed_at)}
        for r in rows
    ]


@router.get("/v1/cpes")
def list_cpes(
    limit: int = Query(100, ge=1, le=1000),
    p: Principal = Depends(require("inventory:read")),
    conn: Connection = Depends(tenant_conn),
) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT c.id, c.canonical_serial, c.vendor, c.model, c.firmware, c.observed_at, "
            "COALESCE(json_agg(json_build_object('protocol', b.protocol, 'connector_id', b.connector_id, "
            "'external_id', b.external_id)) FILTER (WHERE b.id IS NOT NULL), '[]') AS bindings "
            "FROM cpes c LEFT JOIN cpe_protocol_bindings b ON b.cpe_id = c.id AND b.tenant_id = c.tenant_id "
            "GROUP BY c.tenant_id, c.id ORDER BY c.canonical_serial LIMIT :l"
        ),
        {"l": limit},
    )
    return [
        {"id": str(r.id), "canonical_serial": r.canonical_serial, "vendor": r.vendor, "model": r.model,
         "firmware": r.firmware, "bindings": r.bindings,
         "observed_at": r.observed_at.isoformat() if r.observed_at else None, "freshness": _fresh(r.observed_at)}
        for r in rows
    ]
