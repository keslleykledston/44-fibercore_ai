"""NOC incidents: PON mass-outage correlation from ingested snapshots.

Principles
- Evidence only: counts per PON, never customer data. `suspected_cause` is a hint, not a diagnosis.
- Silence is not an outage: incidents are created from observed ONU states in a snapshot. When an Edge goes quiet
  nothing is opened or resolved; the API instead flags the affected incidents as `edge_silent` (suppressed) and lists
  the silent edge itself as a computed alert.
- Deduplicated: one open incident per PON (unique partial index)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection, text

from app.api.deps import Principal, require, tenant_conn
from app.api.routes import EDGE_OFFLINE_AFTER, audit
from app.events import outbox

router = APIRouter()

MIN_ONUS = 5        # smaller PONs never raise a mass-outage incident (one customer down is not a PON event)
OPEN_RATIO = 0.8
RESOLVE_RATIO = 0.5  # hysteresis: prevents flapping around the threshold


def evaluate_pons(conn: Connection, tenant_id: UUID, olt_id: UUID, observed_at: datetime) -> None:
    """Called inside the ingestion transaction. Only ONUs observed in THIS snapshot count."""
    rows = conn.execute(
        text(
            "SELECT p.id AS pon_id, p.pon_path, count(*) AS total, "
            "count(*) FILTER (WHERE u.status IN ('los','offline','dying_gasp')) AS down, "
            "count(*) FILTER (WHERE u.status = 'los') AS los, "
            "count(*) FILTER (WHERE u.status = 'dying_gasp') AS dg "
            "FROM onus u JOIN pon_ports p ON p.id = u.pon_id AND p.tenant_id = u.tenant_id "
            "WHERE u.olt_id = :o AND u.observed_at >= :ts GROUP BY p.id, p.pon_path"
        ),
        {"o": olt_id, "ts": observed_at},
    ).all()
    for r in rows:
        key = f"pon_mass:{r.pon_id}"
        ratio = r.down / r.total if r.total else 0.0
        open_row = conn.execute(
            text("SELECT id, evidence FROM incidents WHERE dedupe_key = :k AND status = 'open' FOR UPDATE"), {"k": key}
        ).first()
        open_inc = open_row.id if open_row else None
        # A partial snapshot (few ONUs reported) is not enough evidence to CLOSE an incident that was opened on more.
        prior = (open_row.evidence or {}).get("onus_observed", 0) if open_row else 0
        enough_to_resolve = r.total >= max(MIN_ONUS, prior // 2)
        evidence = {"pon_path": r.pon_path, "onus_observed": r.total, "onus_down": r.down, "los": r.los,
                    "dying_gasp": r.dg, "ratio": round(ratio, 3)}
        if open_inc is None and r.total >= MIN_ONUS and ratio >= OPEN_RATIO:
            cause = "fiber_or_los" if r.los >= r.down / 2 else ("power" if r.dg >= r.down / 2 else "unknown")
            iid = conn.execute(
                text("INSERT INTO incidents (tenant_id, kind, olt_id, pon_id, dedupe_key, suspected_cause, evidence) "
                     "VALUES (:t,'pon_mass_outage',:o,:p,:k,:c,CAST(:e AS jsonb)) ON CONFLICT DO NOTHING RETURNING id"),
                {"t": tenant_id, "o": olt_id, "p": r.pon_id, "k": key, "c": cause, "e": _j(evidence)},
            ).scalar_one_or_none()
            if iid:
                outbox.enqueue(conn, tenant_id=tenant_id, aggregate_type="incident", aggregate_id=iid,
                               event_type="incident.opened", payload={"kind": "pon_mass_outage", **evidence, "suspected_cause": cause})
        elif open_inc is not None and ratio < RESOLVE_RATIO and enough_to_resolve:
            conn.execute(text("UPDATE incidents SET status='resolved', resolved_at=now(), evidence=CAST(:e AS jsonb) WHERE id=:i"),
                         {"i": open_inc, "e": _j(evidence)})
            outbox.enqueue(conn, tenant_id=tenant_id, aggregate_type="incident", aggregate_id=open_inc,
                           event_type="incident.resolved", payload={"kind": "pon_mass_outage", **evidence})
        elif open_inc is not None and enough_to_resolve:  # still open: refresh counters (never from thin evidence)
            conn.execute(text("UPDATE incidents SET evidence=CAST(:e AS jsonb) WHERE id=:i"), {"i": open_inc, "e": _j(evidence)})


def _j(d: dict) -> str:
    import json

    return json.dumps(d)


@router.get("/v1/incidents")
def list_incidents(
    status: Literal["open", "resolved"] | None = None,
    limit: int = Query(100, ge=1, le=500),
    p: Principal = Depends(require("incidents:read")),
    conn: Connection = Depends(tenant_conn),
) -> dict:
    now = datetime.now(UTC)
    silent_edges = {
        r.id: r for r in conn.execute(text("SELECT id, name, last_heartbeat_at, status FROM edges"))
        if r.status != "revoked" and r.last_heartbeat_at is not None and now - r.last_heartbeat_at > EDGE_OFFLINE_AFTER
    }
    rows = conn.execute(
        text(
            "SELECT i.id, i.kind, i.status, i.suspected_cause, i.evidence, i.opened_at, i.resolved_at, i.acknowledged_at, "
            "o.name AS olt_name, o.edge_id, o.observed_at AS olt_observed_at FROM incidents i "
            "JOIN olts o ON o.id = i.olt_id AND o.tenant_id = i.tenant_id "
            "WHERE (CAST(:s AS text) IS NULL OR i.status = :s) ORDER BY i.opened_at DESC LIMIT :l"
        ),
        {"s": status, "l": limit},
    )
    incidents = [
        {"id": str(r.id), "kind": r.kind, "status": r.status, "suspected_cause": r.suspected_cause, "evidence": r.evidence,
         "olt": r.olt_name, "opened_at": r.opened_at.isoformat(),
         "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
         "acknowledged": r.acknowledged_at is not None,
         # open incident behind a silent edge: state is last-known, cannot be confirmed or cleared right now
         "edge_silent": r.status == "open" and r.edge_id in silent_edges}
        for r in rows
    ]
    alerts = [{"kind": "edge_silent", "edge": e.name, "last_heartbeat_at": e.last_heartbeat_at.isoformat(),
               "note": "no data from this edge; ONU/OLT states behind it are last-known, not offline"}
              for e in silent_edges.values()]
    return {"incidents": incidents, "alerts": alerts}


@router.post("/v1/incidents/{incident_id}/ack")
def ack_incident(incident_id: UUID, p: Principal = Depends(require("incidents:ack")), conn: Connection = Depends(tenant_conn)) -> dict:
    res = conn.execute(
        text("UPDATE incidents SET acknowledged_by=:u, acknowledged_at=now() WHERE id=:i AND acknowledged_at IS NULL RETURNING id"),
        {"u": p.id, "i": incident_id},
    ).first()
    if res is None:
        exists = conn.execute(text("SELECT 1 FROM incidents WHERE id=:i"), {"i": incident_id}).first()
        raise HTTPException(409 if exists else 404, "already acknowledged" if exists else "incident not found")
    audit(conn, p, "incident.ack", "incident", str(incident_id))
    return {"id": str(incident_id), "acknowledged": True}


