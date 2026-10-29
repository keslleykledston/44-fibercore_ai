"""NOC incidents: PON mass-outage correlation from ingested snapshots.

Principles
- Evidence only: counts per PON, never customer data. `suspected_cause` is a hint, not a diagnosis.
- Silence is not an outage: incidents are created from observed ONU states in a snapshot. When an Edge goes quiet
  nothing is opened or resolved; the API instead flags the affected incidents as `edge_silent` (suppressed) and lists
  the silent edge itself as a computed alert.
- Deduplicated: one open incident per PON (unique partial index)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import EDGE_OFFLINE_AFTER, audit
from app.core import diagnostics
from app.core.diagnostics import MIN_DROPPED, OPEN_RATIO  # noqa: F401  (the thresholds live with the rule; re-exported for callers/tests)
from app.events import outbox

router = APIRouter()

RESOLVE_RATIO = 0.5    # hysteresis: prevents flapping around the threshold
# An ONU counts as "recently dropped" if it went online->down within this lookback. It is long enough for an Edge that
# reconnects after a silence/backlog to still show an outage that began while it was away; older drops are chronic.
DROP_WINDOW = timedelta(hours=6)
JOIN_WINDOW = timedelta(minutes=30)   # ONUs dropping this close to an incident opening belong to the same event
# Correlation only runs on snapshots that are fresh by the SERVER clock. Store-and-forward can deliver old snapshots; they
# still update ONU state (history) but must not open or close incidents as if the event were happening now.
EVAL_FRESH_FOR = timedelta(minutes=15)
# An open incident whose covered ONUs have not been reported in enough numbers for this long (e.g. they left the OLT) cannot be
# judged any more; it expires with an explicit reason instead of staying open forever. Edge SILENCE never resolves anything.
INCIDENT_STALE_AFTER = timedelta(hours=24)
DOWN = ("offline", "los", "dying_gasp")


def evaluate_pons(
    conn: Connection, tenant_id: UUID, olt_id: UUID, complete_pons: list[str], serials: list[str], observed_at: datetime
) -> None:
    """Called inside the ingestion transaction, which already holds the OLT row lock (so evaluations of one OLT are
    serialised). Only the ONUs REPORTED IN THIS REQUEST (by serial) count — never inferred from timestamps.

    A mass outage is MANY ONUs DROPPING TOGETHER, not many ONUs being offline: real fleets carry chronically offline
    ONUs (a measured OLT had 37% of its ONTs offline for months). So the rule only looks at ONUs seen going
    online->down inside DROP_WINDOW (`down_since`), and only on snapshots fresh by the server clock. Chronic ones (never
    seen dropping, or dropped long ago) are in neither the numerator nor the denominator. An incident remembers the ONUs
    it covers (`incident_onus`): it resolves when THOSE come back, not merely because the drop window expired."""
    if not serials or not complete_pons:
        return  # only PONs declared complete (full port read) are evaluated
    if observed_at < datetime.now(UTC) - EVAL_FRESH_FOR:
        return  # a replayed/backlogged snapshot is history, not the present state of the network
    rows = conn.execute(
        text(
            "SELECT p.id AS pon_id, p.pon_path, u.id AS onu_id, u.status, u.down_since "
            "FROM onus u JOIN pon_ports p ON p.id = u.pon_id AND p.tenant_id = u.tenant_id "
            "WHERE u.olt_id = :o AND u.serial = ANY(:serials) AND p.pon_path = ANY(:paths)"
        ),
        {"o": olt_id, "serials": serials, "paths": complete_pons},
    ).all()
    by_pon: dict[UUID, list] = {}
    for r in rows:
        by_pon.setdefault(r.pon_id, []).append(r)
    since = observed_at - DROP_WINDOW
    for pon_id, onus in by_pon.items():
        key = f"pon_mass:{pon_id}"
        path = onus[0].pon_path
        online = [r for r in onus if r.status == "online"]
        down = [r for r in onus if r.status in DOWN]
        fresh = [r for r in down if r.down_since is not None and r.down_since >= since]
        open_row = conn.execute(
            text("SELECT id, opened_at, evidence FROM incidents WHERE dedupe_key = :k AND status = 'open' FOR UPDATE"), {"k": key}
        ).first()
        if open_row is None:
            # the opening decision IS rule R-D001 v1 (app/core/diagnostics.py), extracted without changing it
            res = diagnostics.r_d001_v1({
                "pon_path": path, "observed": len(onus), "online": len(online), "recent_drops": len(fresh),
                "los": sum(1 for r in fresh if r.status == "los"), "dying_gasp": sum(1 for r in fresh if r.status == "dying_gasp"),
                "chronic": len(down) - len(fresh), "fresh_data": True})  # freshness was already enforced above (EVAL_FRESH_FOR)
            if res.matched:
                _open_incident(conn, tenant_id, olt_id, pon_id, key, path, len(onus), fresh, len(down) - len(fresh),
                               res.finding["evidence"]["ratio"], observed_at)
            continue
        # open incident: judge the ONUs it covers (plus ONUs that dropped with it afterwards)
        members = {r.onu_id for r in conn.execute(
            text("SELECT onu_id FROM incident_onus WHERE tenant_id=:t AND incident_id=:i"), {"t": tenant_id, "i": open_row.id})}
        legacy = not members
        if legacy:  # opened before membership existed: judge the ONUs reported for the PON (the old rule) rather than orphan it
            members = {r.onu_id for r in onus}
        ev = open_row.evidence or {}
        opened_obs = _parse_dt(ev.get("opened_observed_at")) or open_row.opened_at
        joiners = [] if legacy else [r for r in fresh if r.onu_id not in members
                                     and opened_obs - JOIN_WINDOW <= r.down_since <= opened_obs + JOIN_WINDOW]
        if joiners:
            _add_members(conn, tenant_id, open_row.id, [r.onu_id for r in joiners])
            members |= {r.onu_id for r in joiners}
        reported = [r for r in onus if r.onu_id in members]
        still_down = [r for r in reported if r.status in DOWN]
        ratio = len(still_down) / len(reported) if reported else 0.0
        prior = ev.get("members", ev.get("onus_observed", 0))
        # A partial snapshot (few covered ONUs reported) is not enough evidence to CLOSE an incident opened on more.
        enough_to_resolve = len(reported) >= max(MIN_DROPPED, prior // 2)
        evidence = {"pon_path": path, "onus_observed": len(onus), "onus_down": len(still_down),
                    "los": sum(1 for r in still_down if r.status == "los"),
                    "dying_gasp": sum(1 for r in still_down if r.status == "dying_gasp"),
                    "ratio": round(ratio, 3), "members": max(prior, len(members)),
                    "chronic_offline": len(down) - len(fresh), "opened_observed_at": ev.get("opened_observed_at"),
                    "evidence_at": datetime.now(UTC).isoformat()}
        if ratio < RESOLVE_RATIO and enough_to_resolve:
            _resolve(conn, tenant_id, open_row.id, evidence)
        elif enough_to_resolve:  # still open: refresh counters (never from thin evidence)
            conn.execute(text("UPDATE incidents SET evidence=CAST(:e AS jsonb) WHERE id=:i"), {"i": open_row.id, "e": _j(evidence)})
        elif still_down:  # too few covered ONUs to judge, but the ones reported are still down: the event is alive, renew the deadline
            conn.execute(
                text("UPDATE incidents SET evidence = jsonb_set(evidence, '{evidence_at}', to_jsonb(CAST(:ts AS text))) WHERE id=:i"),
                {"i": open_row.id, "ts": datetime.now(UTC).isoformat()},
            )
        else:
            last = _parse_dt(ev.get("evidence_at")) or open_row.opened_at
            if datetime.now(UTC) - last > INCIDENT_STALE_AFTER:  # members gone/recovered but never enough to judge: expire, say so
                _resolve(conn, tenant_id, open_row.id, {**ev, "resolution": "expired_no_evidence"})


def _resolve(conn: Connection, tenant_id: UUID, incident_id: UUID, evidence: dict) -> None:
    conn.execute(text("UPDATE incidents SET status='resolved', resolved_at=now(), evidence=CAST(:e AS jsonb) WHERE id=:i"),
                 {"i": incident_id, "e": _j(evidence)})
    outbox.enqueue(conn, tenant_id=tenant_id, aggregate_type="incident", aggregate_id=incident_id,
                   event_type="incident.resolved", payload={"kind": "pon_mass_outage", **evidence})


def _parse_dt(v: object) -> datetime | None:
    """Timezone-aware ISO datetime or None. Naive/malformed values (legacy or hand-edited evidence) are invalid, never compared."""
    try:
        d = datetime.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None
    return d if d is not None and d.tzinfo is not None else None


def _add_members(conn: Connection, tenant_id: UUID, incident_id: UUID, onu_ids: list[UUID]) -> None:
    if onu_ids:
        conn.execute(
            text("INSERT INTO incident_onus (tenant_id, incident_id, onu_id) VALUES (:t,:i,:u) ON CONFLICT DO NOTHING"),
            [{"t": tenant_id, "i": incident_id, "u": u} for u in onu_ids],
        )


def _open_incident(conn: Connection, tenant_id: UUID, olt_id: UUID, pon_id: UUID, key: str, path: str, observed: int,
                   fresh: list, chronic: int, ratio: float, observed_at: datetime) -> None:
    los = sum(1 for r in fresh if r.status == "los")
    dg = sum(1 for r in fresh if r.status == "dying_gasp")
    cause = diagnostics.suspected_cause(los, dg, len(fresh))
    evidence = {"pon_path": path, "onus_observed": observed, "onus_down": len(fresh), "los": los, "dying_gasp": dg,
                "ratio": round(ratio, 3), "members": len(fresh), "chronic_offline": chronic,
                "opened_observed_at": observed_at.isoformat(), "evidence_at": datetime.now(UTC).isoformat()}
    iid = conn.execute(
        text("INSERT INTO incidents (tenant_id, kind, olt_id, pon_id, dedupe_key, suspected_cause, evidence) "
             "VALUES (:t,'pon_mass_outage',:o,:p,:k,:c,CAST(:e AS jsonb)) ON CONFLICT DO NOTHING RETURNING id"),
        {"t": tenant_id, "o": olt_id, "p": pon_id, "k": key, "c": cause, "e": _j(evidence)},
    ).scalar_one_or_none()
    if iid:
        _add_members(conn, tenant_id, iid, [r.onu_id for r in fresh])
        outbox.enqueue(conn, tenant_id=tenant_id, aggregate_type="incident", aggregate_id=iid,
                       event_type="incident.opened", payload={"kind": "pon_mass_outage", **evidence, "suspected_cause": cause})


def _j(d: dict) -> str:
    import json

    return json.dumps(d)


@router.get("/v1/incidents")
def list_incidents(
    status: Literal["open", "resolved"] | None = None,
    limit: int = Query(100, ge=1, le=500),
    p: Principal = Depends(require("incidents:read")),
    conn: Connection = TENANT_CONN,
) -> dict:
    cutoff = datetime.now(UTC) - EDGE_OFFLINE_AFTER
    silent = conn.execute(  # filtered and bounded in SQL (tenant scoped by RLS)
        text("SELECT id, name, last_heartbeat_at FROM edges WHERE status <> 'revoked' AND last_heartbeat_at IS NOT NULL "
             "AND last_heartbeat_at < :c ORDER BY last_heartbeat_at LIMIT 100"),
        {"c": cutoff},
    ).all()
    silent_ids = {e.id for e in silent}
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
         "edge_silent": r.status == "open" and r.edge_id in silent_ids}
        for r in rows
    ]
    alerts = [{"kind": "edge_silent", "edge": e.name, "last_heartbeat_at": e.last_heartbeat_at.isoformat(),
               "note": "no data from this edge; ONU/OLT states behind it are last-known, not offline"}
              for e in silent]
    return {"incidents": incidents, "alerts": alerts}


@router.post("/v1/incidents/{incident_id}/ack")
def ack_incident(incident_id: UUID, p: Principal = Depends(require("incidents:ack")), conn: Connection = TENANT_CONN) -> dict:
    res = conn.execute(
        text("UPDATE incidents SET acknowledged_by=:u, acknowledged_at=now() WHERE id=:i AND acknowledged_at IS NULL RETURNING id"),
        {"u": p.id, "i": incident_id},
    ).first()
    if res is None:
        exists = conn.execute(text("SELECT 1 FROM incidents WHERE id=:i"), {"i": incident_id}).first()
        raise HTTPException(409 if exists else 404, "already acknowledged" if exists else "incident not found")
    audit(conn, p, "incident.ack", "incident", str(incident_id))
    return {"id": str(incident_id), "acknowledged": True}


