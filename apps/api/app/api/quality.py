"""QoS-001, cloud half (ADR-0039): the quality read of one ONT.

This adds NO way to write to equipment and NO new engine. The read is built from what the product already holds (the ACS cache as `cpe_state`, the OLT's
state and optical level of the linked ONU) and, for the complete mode, REFERENCES the SD-001 runs the caller already has (their group id): it never starts a
TR-143 test, never talks to the Edge, never reads the ACS. Active tests (ping/DNS) are not part of this router yet. The whole router answers 403
`feature_disabled` while the tenant flag `quality_diagnostics` is off; turning it off leaves SD-001 and the ONU views untouched."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import features, quality

router = APIRouter()
SPEED_REF_MAX_AGE = timedelta(hours=1)   # a referenced SD-001 group must be recent: an old result is history, not part of this read
HISTORY = 20


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["quick", "full"] = "quick"
    speed_group_id: UUID | None = None   # complete mode only: the SD-001 group (one run per direction) to reference


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "quality_diagnostics")


def _cpe_or_404(conn: Connection, cpe_id: UUID):
    c = conn.execute(text("SELECT id FROM cpes WHERE id = :i"), {"i": cpe_id}).first()
    if c is None:
        raise HTTPException(404, "cpe not found")
    return c


def _facts(conn: Connection, cpe_id: UUID, now: datetime, speed_group: UUID | None) -> tuple[quality.Facts, list[UUID]]:
    rows = tuple(quality.StateRow(r.metric, r.scope, r.value, r.captured_at) for r in conn.execute(
        text("SELECT metric, scope, value, captured_at FROM cpe_state WHERE cpe_id = :c ORDER BY metric, scope"), {"c": cpe_id}))
    o = conn.execute(
        text("SELECT u.status, u.rx_dbm, u.observed_at FROM onu_cpe_links l JOIN onus u ON u.id = l.onu_id AND u.tenant_id = l.tenant_id "
             "WHERE l.cpe_id = :c AND l.status = 'confirmed' ORDER BY u.observed_at DESC NULLS LAST LIMIT 1"), {"c": cpe_id}).first()
    onu = quality.OnuFact(o.status, float(o.rx_dbm) if o.rx_dbm is not None else None, o.observed_at) if o else None
    speed: tuple[quality.SpeedFact, ...] = ()
    groups: list[UUID] = []
    if speed_group is not None:
        runs = conn.execute(
            text("SELECT r.id, r.group_id, r.direction, r.outcome, r.mbps, r.created_at, COALESCE(e.target_kind, 'CORE') AS kind FROM speed_test_runs r "
                 "LEFT JOIN speed_endpoints e ON e.tenant_id = r.tenant_id AND e.id = r.endpoint_id "
                 "WHERE r.group_id = :g AND r.cpe_id = :c AND r.created_at > :since AND r.created_at <= :until"),
            {"g": speed_group, "c": cpe_id, "since": now - SPEED_REF_MAX_AGE, "until": now + timedelta(seconds=quality.CLOCK_SKEW_S)}).all()
        if not runs:
            raise HTTPException(422, "speed_group_not_found_for_this_cpe_or_too_old")
        groups = [speed_group]
        speed = tuple(quality.SpeedFact(str(r.id), str(r.group_id), r.direction, r.kind, r.outcome, float(r.mbps) if r.mbps is not None else None, r.created_at)
                      for r in runs)
    return quality.Facts(now=now, cpe_state=rows, onu=onu, speed=speed), groups


def _view(r) -> dict:
    return {"id": str(r.id), "cpe_id": str(r.cpe_id), "mode": r.mode, "state": r.state, "schema_version": r.schema_version, "created_at": r.created_at.isoformat(),
            "metrics": r.metrics, "hypotheses": r.hypotheses, "summary": r.summary, "speed_group_ids": [str(g) for g in r.speed_group_ids]}


COLS = "id, cpe_id, mode, state, schema_version, created_at, metrics, hypotheses, summary, speed_group_ids"


@router.get("/v1/cpes/{cpe_id}/quality/capabilities")
def capabilities(cpe_id: UUID, p: Principal = Depends(require("diagnostics:quality_read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    _cpe_or_404(conn, cpe_id)
    full_flag = features.enabled(conn, p.tenant_id, "quality_full")
    return {
        "cpe_id": str(cpe_id),
        "modes": {
            "quick": {"offered": p.can("diagnostics:quality_run"), "reason": None if p.can("diagnostics:quality_run") else "not_permitted"},
            "full": {"offered": full_flag and p.can("diagnostics:quality_run_full"),
                     "reason": None if full_flag and p.can("diagnostics:quality_run_full") else ("feature_disabled" if not full_flag else "not_permitted")},
        },
        # ping/DNS are active tests that write to the device: they need the bench catalog, the Connection Request path and their own flag (not shipped here)
        "active_tests": {"offered": False, "reason": "not_available"},
        "speed": {"reference_only": True},
        "ttl_s": quality.TTL_S,
    }


@router.post("/v1/cpes/{cpe_id}/quality/runs", status_code=201)
def request_run(
    cpe_id: UUID, body: RunIn, response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    p: Principal = Depends(require("diagnostics:quality_run")), conn: Connection = TENANT_CONN,
) -> dict:
    _flag(conn, p)
    _cpe_or_404(conn, cpe_id)
    if body.mode == "full":
        if not (p.can("diagnostics:quality_run_full") and features.enabled(conn, p.tenant_id, "quality_full")):
            raise HTTPException(403, "forbidden" if not p.can("diagnostics:quality_run_full") else "feature_disabled")
    elif body.speed_group_id is not None:
        raise HTTPException(422, "speed_group_id_needs_full_mode")
    # the same key arriving twice at once: the second waits for the first to commit and then finds its run
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"quality-idempotency|{p.tenant_id}|{p.id}|{idempotency_key}"})
    prior = conn.execute(text(f"SELECT {COLS}, cpe_id AS c2 FROM quality_runs WHERE requested_by = :u AND idempotency_key = :k"),  # noqa: S608
                         {"u": p.id, "k": idempotency_key}).first()
    if prior is not None:
        asked = [body.speed_group_id] if body.mode == "full" and body.speed_group_id else []
        if prior.cpe_id != cpe_id or prior.mode != body.mode or list(prior.speed_group_ids) != asked:   # the key names ONE read, with its exact reference
            raise HTTPException(409, "idempotency_key_reused_for_another_read")
        response.status_code = 200
        return _view(prior)
    now = datetime.now(UTC)
    facts, groups = _facts(conn, cpe_id, now, body.speed_group_id if body.mode == "full" else None)
    metrics = quality.build_metrics(facts)
    if body.mode == "full" and not groups:   # the complete read states what it did not have, instead of silently looking like the quick one
        metrics.append(quality.metric("speed.download_mbps", "CORE", "not_available", source="SD001", scope="WAN_UNCLASSIFIED", now=now,
                                      details={"reason": "no_speed_run_referenced"}))
    hyps = quality.hypotheses(metrics, facts)
    summary = quality.summarize(metrics, hyps)
    state = quality.run_state(metrics)
    row = conn.execute(
        text(f"INSERT INTO quality_runs (tenant_id, cpe_id, mode, state, requested_by, idempotency_key, schema_version, metrics, hypotheses, summary, speed_group_ids) "  # noqa: S608
             f"VALUES (:t, :c, :m, :s, :u, :k, :v, CAST(:me AS jsonb), CAST(:h AS jsonb), CAST(:su AS jsonb), :g) RETURNING {COLS}"),
        {"t": p.tenant_id, "c": cpe_id, "m": body.mode, "s": state, "u": p.id, "k": idempotency_key, "v": quality.SCHEMA_VERSION,
         "me": json.dumps(metrics), "h": json.dumps(hyps), "su": json.dumps(summary), "g": groups}).one()
    # the audit trail carries who, which CPE, which mode and the outcome, never a metric value
    audit(conn, p, "quality.requested", "cpe", str(cpe_id), {"run_id": str(row.id), "mode": body.mode, "state": state, "metrics": len(metrics), "hypotheses": len(hyps)})
    return _view(row)


@router.get("/v1/cpes/{cpe_id}/quality/runs")
def list_runs(cpe_id: UUID, p: Principal = Depends(require("diagnostics:quality_read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    _cpe_or_404(conn, cpe_id)
    rows = conn.execute(text(f"SELECT {COLS} FROM quality_runs WHERE cpe_id = :c ORDER BY created_at DESC, id LIMIT :n"),  # noqa: S608
                        {"c": cpe_id, "n": HISTORY}).all()
    return {"cpe_id": str(cpe_id), "runs": [_view(r) for r in rows]}


@router.get("/v1/cpes/{cpe_id}/quality/runs/{run_id}")
def get_run(cpe_id: UUID, run_id: UUID, p: Principal = Depends(require("diagnostics:quality_read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(text(f"SELECT {COLS} FROM quality_runs WHERE id = :i AND cpe_id = :c"), {"i": run_id, "c": cpe_id}).first()  # noqa: S608
    if r is None:
        raise HTTPException(404, "run not found")
    return _view(r)
