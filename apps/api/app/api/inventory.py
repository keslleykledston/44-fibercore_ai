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

from app.api.deps import TENANT_CONN, Principal, require
from app.api.noc import evaluate_pons
from app.api.routes import audit
from app.core import features
from app.core.capabilities import catalog_for
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
    canonical_serial: Short  # canonical form: trimmed + upper case (the device chooses its own serial; the ERP matches on upper())
    vendor: Short | None = None
    model: Short | None = None
    firmware: Short | None = None
    binding: CpeBinding

    @field_validator("canonical_serial")
    @classmethod
    def _canonical(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("canonical_serial is empty")
        return v


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
    body: OltSnapshot, p: Principal = Depends(require("inventory:write")), conn: Connection = TENANT_CONN
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
                "VALUES (:t,:o,:pi,:s,:st,:rx,:ts, CASE WHEN CAST(:st AS text) = 'online' THEN LEAST(CAST(:ts AS timestamptz), now()) END) "
                "ON CONFLICT (tenant_id, olt_id, serial) DO UPDATE SET pon_id=EXCLUDED.pon_id, status=EXCLUDED.status, "
                "rx_dbm=EXCLUDED.rx_dbm, observed_at=EXCLUDED.observed_at, "
                "last_online_at = CASE WHEN EXCLUDED.status = 'online' "
                "THEN LEAST(EXCLUDED.observed_at, now()) ELSE onus.last_online_at END, "
                # Transition times are clamped to the server clock (an Edge may be ahead by MAX_FUTURE_SKEW): no future
                # state is persisted. down_since only records a REAL transition (seen online, now seen down). An ONU first
                # seen down, or coming from 'unknown', has no known drop time and stays NULL: chronic as far as
                # correlation can tell.
                "down_since = CASE WHEN EXCLUDED.status = 'online' THEN NULL "
                "WHEN onus.status = 'online' AND EXCLUDED.status IN ('offline','los','dying_gasp') THEN LEAST(EXCLUDED.observed_at, now()) "
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
    body: CpeSnapshot, p: Principal = Depends(require("inventory:write")), conn: Connection = TENANT_CONN
) -> dict:
    _bound_edge(p, body.edge_id)
    all_serials = [c.canonical_serial for c in body.cpes]
    # Serialise concurrent snapshots per CLAIM key (tenant, serial, connector, protocol) — also for serials that do not exist yet, which
    # row locks cannot cover. Sorted and taken sequentially, so two overlapping batches acquire them in the same order (no deadlock).
    # The unique index is the backstop.
    keys = sorted({f"{p.tenant_id}|{c.canonical_serial}|{c.binding.connector_id}|{c.binding.protocol}" for c in body.cpes}
                  | {f"{p.tenant_id}|bind|{c.binding.connector_id}|{c.binding.protocol}|{c.binding.external_id}" for c in body.cpes})
    if keys:  # one statement per key, run by the driver in this exact order (a single SELECT over unnest() would not guarantee it)
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), [{"k": k} for k in keys])
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
        return {"status": "ignored_stale", "cpes": 0, "skipped": skipped, "conflicts": 0}
    # A serial is only a CLAIM made by the device. One CPE has ONE external id per (connector, protocol): a claim that names a
    # different one (than stored, or than another claim in this very batch) is IGNORED and counted, never merged into the existing
    # CPE (no second binding, no vendor/model overwrite). Ignoring instead of failing keeps one hostile device from blocking the rest.
    stored: dict[tuple, str] = {
        (r.canonical_serial, r.connector_id, r.protocol): r.external_id
        for r in conn.execute(
            text("SELECT c.canonical_serial, b.connector_id, b.protocol, b.external_id FROM cpes c JOIN cpe_protocol_bindings b "
                 "ON b.cpe_id = c.id AND b.tenant_id = c.tenant_id WHERE c.tenant_id = :t AND c.canonical_serial = ANY(:s)"),
            {"t": p.tenant_id, "s": [c.canonical_serial for c in fresh]},
        )
    }
    claimed: dict[tuple, set[str]] = {}
    for c in fresh:
        claimed.setdefault((c.canonical_serial, c.binding.connector_id, c.binding.protocol), set()).add(c.binding.external_id)
    linked_to: dict[tuple, str] = {  # external ids that already belong to ANOTHER serial (a hostile/mistaken claim must not cost the batch)
        (r.connector_id, r.protocol, r.external_id): r.canonical_serial
        for r in conn.execute(
            text("SELECT b.connector_id, b.protocol, b.external_id, c.canonical_serial FROM cpe_protocol_bindings b JOIN cpes c "
                 "ON c.id = b.cpe_id AND c.tenant_id = b.tenant_id WHERE b.tenant_id = :t AND b.external_id = ANY(:x)"),
            {"t": p.tenant_id, "x": [c.binding.external_id for c in fresh]},
        )
    }
    owners_of_binding: dict[tuple, set[str]] = {}  # the same external id claimed by DIFFERENT serials in one batch: neither can be trusted
    for c in fresh:
        owners_of_binding.setdefault((c.binding.connector_id, c.binding.protocol, c.binding.external_id), set()).add(c.canonical_serial)
    kept = []
    seen_claims: set[tuple] = set()
    repeats = 0
    for c in fresh:
        k = (c.canonical_serial, c.binding.connector_id, c.binding.protocol)
        if len(claimed[k]) > 1 or stored.get(k, c.binding.external_id) != c.binding.external_id:
            continue
        bk = (c.binding.connector_id, c.binding.protocol, c.binding.external_id)
        if len(owners_of_binding[bk]) > 1 or linked_to.get(bk, c.canonical_serial) != c.canonical_serial:
            continue
        if k in seen_claims:  # identical repeat of an accepted claim: one row per claim key reaches the upserts (not a conflict)
            repeats += 1
            continue
        seen_claims.add(k)
        kept.append(c)
    conflicts = len(fresh) - len(kept) - repeats
    fresh = kept
    if not fresh:
        return {"status": "accepted", "cpes": 0, "skipped": skipped, "conflicts": conflicts}
    serials = [c.canonical_serial for c in fresh]
    first_per_serial: dict[str, CpeIn] = {}
    for c in fresh:
        first_per_serial.setdefault(c.canonical_serial, c)
    conn.execute(
        text(
            "INSERT INTO cpes (tenant_id, edge_id, canonical_serial, vendor, model, firmware, observed_at) "
            "VALUES (:t,:e,:s,:v,:m,:f,:o) ON CONFLICT (tenant_id, canonical_serial) DO UPDATE SET vendor=EXCLUDED.vendor, "
            "model=EXCLUDED.model, firmware=EXCLUDED.firmware, observed_at=EXCLUDED.observed_at "
            "WHERE cpes.edge_id = EXCLUDED.edge_id AND (cpes.observed_at IS NULL OR cpes.observed_at <= EXCLUDED.observed_at)"
        ),
        # ONE row per serial (first claim wins): a device announced over several protocols/connectors still maps to a single cpes row;
        # its extra bindings are inserted below, one per claim key.
        [{"t": p.tenant_id, "e": body.edge_id, "s": c.canonical_serial, "v": c.vendor, "m": c.model, "f": c.firmware, "o": body.observed_at}
         for c in first_per_serial.values()],
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
    conn.execute(
        text(
            "INSERT INTO cpe_protocol_bindings (tenant_id, cpe_id, protocol, external_id, connector_id, observed_at) "
            "VALUES (:t,:ci,:p,:x,:c,:o) ON CONFLICT (tenant_id, connector_id, protocol, external_id) "
            "DO UPDATE SET observed_at = GREATEST(cpe_protocol_bindings.observed_at, EXCLUDED.observed_at)"
        ),
        [{"t": p.tenant_id, "ci": ids[c.canonical_serial], "p": c.binding.protocol, "x": c.binding.external_id,
          "c": c.binding.connector_id, "o": body.observed_at} for c in fresh],
    )
    return {"status": "accepted", "cpes": len(fresh), "skipped": skipped, "conflicts": conflicts}


# ---- reads ------------------------------------------------------------------------------------
def _prov(source: str, observed_at: datetime | None) -> dict:
    """Provenance envelope (ADR-0020): where a block came from, when it was observed, and how fresh that is NOW.
    quality is fresh|stale|unknown; `conflict` is reserved for a second source disagreeing and is never produced from a single source."""
    return {"source": source, "observed_at": observed_at.isoformat() if observed_at else None, "quality": _fresh(observed_at)}


def _fresh(ts: datetime | None) -> str:
    if ts is None:
        return "unknown"
    return "fresh" if datetime.now(UTC) - ts <= FRESH_FOR else "stale"


@router.get("/v1/olts")
def list_olts(
    limit: int = Query(100, ge=1, le=1000),
    p: Principal = Depends(require("inventory:read")),
    conn: Connection = TENANT_CONN,
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
    conn: Connection = TENANT_CONN,
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


@router.get("/v1/onus/{onu_id}")
def onu_360(
    onu_id: UUID,
    p: Principal = Depends(require("inventory:read")),
    conn: Connection = TENANT_CONN,
) -> dict:
    """ONU 360: everything the inventory knows about ONE ONU, with where each piece came from. Read-only. Personal data is NOT here:
    the subscriber lives behind its own route (customers:read, audited). The open incident needs incidents:read; without it the field
    is absent and `incident_hidden` is true (never a misleading "no incident")."""
    u = conn.execute(
        text(
            "SELECT u.id, u.olt_id, u.pon_id, u.serial, u.status, u.rx_dbm, u.observed_at, u.last_online_at, u.down_since, "
            "pp.pon_path, o.name AS olt_name, o.vendor, o.model, o.firmware, o.support_level, o.observed_at AS olt_observed_at "
            "FROM onus u JOIN olts o ON o.id = u.olt_id AND o.tenant_id = u.tenant_id "
            "LEFT JOIN pon_ports pp ON pp.id = u.pon_id AND pp.tenant_id = u.tenant_id WHERE u.id = :i"
        ),
        {"i": onu_id},
    ).first()
    if u is None:
        raise HTTPException(404, "onu not found")
    pon, pon_seen = None, None
    if u.pon_id:
        t = conn.execute(
            text("SELECT count(*) AS total, count(*) FILTER (WHERE status = 'online') AS online, max(observed_at) AS seen "
                 "FROM onus WHERE pon_id = :p"),
            {"p": u.pon_id},
        ).one()
        # the counts are the LAST KNOWN state of the port, so they carry the age of the newest observation they rest on
        pon_seen = t.seen
        pon = {"path": u.pon_path, "onus": t.total, "online": t.online,
               "observed_at": t.seen.isoformat() if t.seen else None, "freshness": _fresh(t.seen)}
    can_incidents = p.can("incidents:read")
    inc = conn.execute(
        text(
            "SELECT i.id, i.kind, i.suspected_cause, i.opened_at FROM incident_onus io JOIN incidents i "
            "ON i.id = io.incident_id AND i.tenant_id = io.tenant_id "
            "WHERE io.onu_id = :o AND i.status = 'open' ORDER BY i.opened_at DESC LIMIT 1"
        ),
        {"o": onu_id},
    ).first() if can_incidents else None
    return {
        "id": str(u.id), "serial": u.serial, "status": u.status, "rx_dbm": float(u.rx_dbm) if u.rx_dbm is not None else None,
        "observed_at": u.observed_at.isoformat() if u.observed_at else None, "freshness": _fresh(u.observed_at),
        "last_online_at": u.last_online_at.isoformat() if u.last_online_at else None,
        "down_since": u.down_since.isoformat() if u.down_since else None,
        "olt": {"id": str(u.olt_id), "name": u.olt_name, "vendor": u.vendor, "model": u.model, "firmware": u.firmware,
                "support_level": u.support_level, "observed_at": u.olt_observed_at.isoformat() if u.olt_observed_at else None,
                "freshness": _fresh(u.olt_observed_at)},
        "pon": pon,
        "incident": ({"id": str(inc.id), "kind": inc.kind, "suspected_cause": inc.suspected_cause,
                      "opened_at": inc.opened_at.isoformat()} if inc else None),
        "incident_hidden": not can_incidents,
        "provenance": {
            "state": _prov("olt_snapshot", u.observed_at),
            "olt": _prov("olt_snapshot", u.olt_observed_at),
            **({"pon": _prov("olt_snapshot", pon_seen)} if pon else {}),
        },
        "source": "olt_snapshot",  # where status/rx came from (CLI/SNMP read by the Edge); nothing here is written to the network
    }


@router.get("/v1/onus/{onu_id}/customer")
def onu_customer(
    onu_id: UUID,
    p: Principal = Depends(require("customers:read")),
    conn: Connection = TENANT_CONN,
) -> dict:
    """Subscriber linked to an ONU (personal data): customers:read only, every view audited."""
    if conn.execute(text("SELECT 1 FROM onus WHERE id = :i"), {"i": onu_id}).first() is None:
        raise HTTPException(404, "onu not found")
    c = conn.execute(
        text(
            "SELECT c.display_name, c.document_last4, c.contract_status FROM associations a "
            "JOIN customers c ON c.id = a.customer_id AND c.tenant_id = a.tenant_id WHERE a.onu_id = :o AND a.status = 'approved'"
        ),
        {"o": onu_id},
    ).first()
    pending = conn.execute(text("SELECT count(*) FROM associations WHERE onu_id = :o AND status = 'suggested'"), {"o": onu_id}).scalar_one()
    out: dict = {"association": "approved" if c else ("suggested" if pending else "none"), "pending_suggestions": pending}
    if c:
        out.update(display_name=c.display_name, document_last4=c.document_last4, contract_status=c.contract_status)
    audit(conn, p, "onu360.customer.view", "onu", str(onu_id), {})  # access to personal data is logged
    return out


def _capabilities(conn: Connection, tenant_id: UUID, kind: str, vendor: str | None, model: str | None, firmware: str | None) -> list[dict]:
    """Catalog x registry for ONE profile. Unknown profile, unknown firmware or no row => status unknown / certification identified."""
    from app.api.jobs import OPERATIONS, _blocked_reason  # local: jobs imports this module's siblings at load time

    rows: dict[tuple[str, str], object] = {}
    if vendor and model and firmware:
        for r in conn.execute(
            text("SELECT protocol, operation, status, certification, verified_at, evidence_ref FROM device_capabilities "
                 "WHERE tenant_id = :t AND lower(vendor) = lower(:v) AND lower(model) = lower(:m) AND firmware = :f"),
            {"t": tenant_id, "v": vendor.strip(), "m": model.strip(), "f": firmware.strip()},
        ):
            rows[(r.protocol, r.operation)] = r
    out = []
    for e in catalog_for(kind, OPERATIONS):
        r = rows.get((e.protocol, e.operation))
        out.append({
            "name": e.operation, "protocol": e.protocol, "status": r.status if r else "unknown",
            "certification": r.certification if r else "identified", "vendor": vendor, "model": model, "firmware": firmware,
            "writes": e.writes,
            # the SAME gate the job engine applies; the registry never opens a write by itself
            "blocked_reason": _blocked_reason(e.operation),
            "verified_at": r.verified_at.isoformat() if r and r.verified_at else None, "evidence_ref": r.evidence_ref if r else None,
        })
    return out


@router.get("/v1/cpes/{cpe_id}/capabilities")
def cpe_capabilities(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> list[dict]:
    features.ensure(conn, p.tenant_id, "capability_registry")
    c = conn.execute(text("SELECT vendor, model, firmware FROM cpes WHERE id = :i"), {"i": cpe_id}).first()
    if c is None:
        raise HTTPException(404, "cpe not found")
    return _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware)


@router.get("/v1/olts/{olt_id}/capabilities")
def olt_capabilities(olt_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> list[dict]:
    features.ensure(conn, p.tenant_id, "capability_registry")
    o = conn.execute(text("SELECT vendor, model, firmware FROM olts WHERE id = :i"), {"i": olt_id}).first()
    if o is None:
        raise HTTPException(404, "olt not found")
    return _capabilities(conn, p.tenant_id, "olt", o.vendor, o.model, o.firmware)


@router.get("/v1/cpes")
def list_cpes(
    limit: int = Query(100, ge=1, le=1000),
    p: Principal = Depends(require("inventory:read")),
    conn: Connection = TENANT_CONN,
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
