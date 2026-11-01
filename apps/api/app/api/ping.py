"""Ping test TR-143 IPPing, cloud half (ADR-0030 amendment line Q1, ADR-0039).

This adds NO way to write to equipment. A request here is exactly the job the engine already knows (preview, then submit) for the bench operation `ping_test`;
everything after it is unchanged: the global gate (HOMOLOGATED_WRITES stays empty), the bench gate (bench target, registry evidence, the owner's prior
single-use authorization), another person's approval, the signed envelope and the Edge's own refusals. What this layer adds is the screen's contract (what this
CPE can do, with which logical destinations), the shared per-CPE reservation (one diagnostic at a time, whichever kind) with an hourly ceiling, and the run
history with the figures the cloud computed. The whole router answers 403 `feature_disabled` while the tenant flag `quality_active_tests` is off.

There is no DNS test (the bench models expose no NSLookup object) and no jitter (the device reports only min/avg/max): the screen shows the spread between the
slowest and the fastest reply under that name.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app.api import jobs
from app.api.deps import TENANT_CONN, Principal, require
from app.api.inventory import _capabilities
from app.api.routes import audit
from app.core import bench, features, probe

router = APIRouter()

OPERATION = "ping_test"
_JOB_STATUS = {"PENDING_APPROVAL": "awaiting_approval", "APPROVED": "queued", "DISPATCHED": "collecting", "ACCEPTED": "collecting",
               "DEVICE_PENDING": "collecting", "VERIFYING": "collecting", "CANCELLED": "cancelled", "EXPIRED": "expired",
               "FAILED": "failed", "UNKNOWN": "unknown", "SUCCEEDED": "unknown", "PREVIEWED": "queued"}

RUN_COLS = ("r.id, r.cpe_id, r.job_id, r.target_id, r.created_at, r.outcome, r.success_count, r.failure_count, r.loss_pct, r.avg_ms, r.min_ms, r.max_ms, "
            "r.reason, r.completed_at, j.status AS job_status, j.result AS job_result")


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "quality_active_tests")


def _run_view(r) -> dict:
    status = r.outcome or _JOB_STATUS.get(r.job_status, "unknown")
    detail = (r.job_result or {}).get("detail") if r.job_status in ("FAILED", "UNKNOWN") and isinstance(r.job_result, dict) else None
    spread = r.max_ms - r.min_ms if r.max_ms is not None and r.min_ms is not None else None
    return {
        "id": str(r.id), "cpe_id": str(r.cpe_id), "job_id": str(r.job_id), "target_id": r.target_id, "status": status, "created_at": r.created_at.isoformat(),
        "sent": r.success_count + r.failure_count if r.success_count is not None else None,
        "success": r.success_count, "failure": r.failure_count,
        # the figures exist only for a finished test that reported them; `null` is shown as "—", never as 0 (a 100 % loss has no times)
        "loss_pct": float(r.loss_pct) if r.loss_pct is not None else None, "avg_ms": r.avg_ms, "min_ms": r.min_ms, "max_ms": r.max_ms,
        # the device gives no per-reply times: this is the slowest minus the fastest reply, NOT jitter
        "spread_ms": spread,
        "reason": r.reason or (str(detail)[:60] if detail else None), "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }


def _cpe_or_404(conn: Connection, cpe_id: UUID):
    c = conn.execute(text("SELECT id, vendor, model, firmware FROM cpes WHERE id = :i"), {"i": cpe_id}).first()
    if c is None:
        raise HTTPException(404, "cpe not found")
    return c


def _bench_edge(conn: Connection, cpe_id: UUID):
    """The Edge that would run a test on this CPE: the one its bench target is registered to (None for a CPE that is not a bench target)."""
    return conn.execute(text("SELECT edge_id FROM bench_targets WHERE cpe_id = :c"), {"c": cpe_id}).scalar()


def _targets(conn: Connection, edge_id=None) -> list[dict]:
    """The catalog. `ready` = enabled and owned by the Edge that would run the test (the Edge also refuses an id it does not list)."""
    rows = conn.execute(text("SELECT id, label, target_kind, region, enabled, edge_id FROM probe_targets ORDER BY target_kind, id")).all()
    return [{"id": r.id, "label": r.label, "target_kind": r.target_kind, "region": r.region, "enabled": r.enabled,
             "ready": bool(r.enabled and edge_id is not None and r.edge_id == edge_id)} for r in rows]


def _first_run_open(conn: Connection, tenant_id: UUID, cpe_id: UUID, target_ids: list[str]) -> bool:
    """An owner's `first_run` authorization (ADR-0030 amendment) is open and inside its window for this CPE and one of the destinations asked about; it is bound
    to the EXACT parameters (`params_hash` of {target}). The gate re-decides at submit, approve and dispatch."""
    hashes = sorted({bench.params_hash({"target": t}) for t in target_ids})
    return bool(hashes) and conn.execute(
        text("SELECT 1 FROM bench_authorizations WHERE tenant_id = :t AND cpe_id = :c AND operation = :o AND state = 'open' AND first_run "
             "AND now() >= window_start AND now() < window_end AND params_hash = ANY(:h) LIMIT 1"),
        {"t": tenant_id, "c": cpe_id, "o": OPERATION, "h": hashes}).first() is not None


def _state(p: Principal, caps: list[dict], is_bench: bool, first_run_open: bool) -> dict:
    """Why a ping test can or cannot be requested right now, in the ORDER a person can act on it. Same decision the request applies (it re-checks)."""
    entry = next((c for c in caps if c["name"] == OPERATION and c["protocol"] == "tr069"), None)
    reason = None
    if not (p.can("diagnostics:ping_run") and p.can("jobs:request")):
        reason = "not_permitted"
    elif not is_bench:
        reason = "operation_not_homologated"   # every CPE outside the bench list: the global gate (HOMOLOGATED_WRITES) stays empty
    elif entry is None or entry["status"] != "supported" or not (
        entry["certification"] in ("observed", "certified")
        or (first_run_open and entry["certification"] == "identified" and entry["evidence_ref"] and entry["verified_at"])
    ):
        reason = "capability_not_observed"
    return {"operation": OPERATION, "offered": reason is None, "reason": reason,
            "certification": entry["certification"] if entry else "identified", "status": entry["status"] if entry else "unknown"}


@router.get("/v1/cpes/{cpe_id}/ping/capabilities")
def capabilities(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    c = _cpe_or_404(conn, cpe_id)
    caps = _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware)
    is_bench = bool(conn.execute(text("SELECT 1 FROM bench_targets WHERE cpe_id = :c"), {"c": cpe_id}).first())
    tg = _targets(conn, _bench_edge(conn, cpe_id))
    state = _state(p, caps, is_bench, _first_run_open(conn, p.tenant_id, cpe_id, [t["id"] for t in tg]))
    return {
        "cpe_id": str(cpe_id), "bench_target": is_bench, "edge_support": bench.PING_EDGE_SUPPORT, "test": state, "targets": tg,
        # what the shape of the test is, so the screen can say it: fixed by the Edge, not chosen by the caller
        "shape": {"repetitions": probe.REPETITIONS, "timeout_ms": 1000},
        "limits": {"per_cpe_live": 1, "per_cpe_per_hour": probe.MAX_RUNS_PER_HOUR},
        # honest about what this model cannot do: no DNS object on the bench models, and the device reports no per-reply times (no jitter)
        "unsupported": ["dns_test", "jitter"],
        "ready": bench.PING_EDGE_SUPPORT and state["offered"] and any(t["ready"] for t in tg),
    }


@router.get("/v1/cpes/{cpe_id}/ping/runs")
def list_runs(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    _cpe_or_404(conn, cpe_id)
    rows = conn.execute(
        text(f"SELECT {RUN_COLS} FROM ping_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id "  # noqa: S608
             "WHERE r.cpe_id = :c ORDER BY r.created_at DESC LIMIT 20"), {"c": cpe_id}).all()
    return {"cpe_id": str(cpe_id), "items": [_run_view(r) for r in rows]}


@router.get("/v1/cpes/{cpe_id}/ping/runs/{run_id}")
def get_run(cpe_id: UUID, run_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(
        text(f"SELECT {RUN_COLS} FROM ping_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id "  # noqa: S608
             "WHERE r.id = :i AND r.cpe_id = :c"), {"i": run_id, "c": cpe_id}).first()
    if r is None:
        raise HTTPException(404, "run not found")
    return _run_view(r)


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str = Field(min_length=2, max_length=31, pattern=r"^[a-z0-9][a-z0-9-]{1,30}$")


def _blocked(conn: Connection, p: Principal, response: Response, cpe_id: UUID, reason: str, body: RunIn, job_id: str | None = None) -> dict:
    """A refusal is an answer with a status and an audit row, not an exception: the transaction commits so the refusal stays on record."""
    audit(conn, p, "ping.blocked", "cpe", str(cpe_id), {"target_id": body.target_id, "reason": reason, **({"job_id": job_id} if job_id else {})})
    response.status_code = 409
    return {"outcome": "blocked", "reason": reason, "run": None}


def _run_by_job(conn: Connection, job_id: UUID) -> dict | None:
    r = conn.execute(
        text(f"SELECT {RUN_COLS} FROM ping_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id WHERE r.job_id = :j"),  # noqa: S608
        {"j": job_id}).first()
    return _run_view(r) if r else None


@router.post("/v1/cpes/{cpe_id}/ping/runs", status_code=201)
def request_run(
    cpe_id: UUID, body: RunIn, response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    p: Principal = Depends(require("diagnostics:ping_run")), conn: Connection = TENANT_CONN,
) -> dict:
    _flag(conn, p)
    if not p.can("jobs:request"):
        raise HTTPException(403, "forbidden")
    c = _cpe_or_404(conn, cpe_id)
    params = {"target": body.target_id}
    # the same key arriving twice at once: the second waits here for the first to COMMIT and then finds its run, instead of reaching the reservation first and
    # being refused as busy by the very run it is a retry of (order is always key -> slots)
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"job-idempotency|{p.tenant_id}|{idempotency_key}"})
    if conn.execute(text("SELECT 1 FROM jobs WHERE idempotency_key = :k"), {"k": idempotency_key}).first():
        view = jobs.create_preview(jobs.PreviewIn(operation=OPERATION, target_id=cpe_id, params=params), idempotency_key, p, conn)
        run = _run_by_job(conn, UUID(view["id"]))
        response.status_code = 200
        return {"outcome": "existing", "reason": None if run else "cancelled", "run": run}
    caps = _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware)
    is_bench = bool(conn.execute(text("SELECT 1 FROM bench_targets WHERE cpe_id = :c"), {"c": cpe_id}).first())
    st = _state(p, caps, is_bench, _first_run_open(conn, p.tenant_id, cpe_id, [body.target_id]))
    if not st["offered"]:
        return _blocked(conn, p, response, cpe_id, st["reason"], body)
    tg = next((t for t in _targets(conn, _bench_edge(conn, cpe_id)) if t["id"] == body.target_id), None)
    if tg is None or not tg["ready"]:
        return _blocked(conn, p, response, cpe_id, "target_unavailable", body)
    busy = probe.busy_reason(conn, p.tenant_id, cpe_id)   # takes the per-tenant reservation lock, held to the end of this transaction
    if busy:
        return _blocked(conn, p, response, cpe_id, busy, body)
    view = jobs.create_preview(jobs.PreviewIn(operation=OPERATION, target_id=cpe_id, params=params), idempotency_key, p, conn)
    try:
        view = jobs.submit(UUID(view["id"]), p, conn)
    except HTTPException as exc:   # the write gate (or anything the engine refuses): the request ends here, visibly, and leaves no live job
        jobs.cas(conn, UUID(view["id"]), "CANCELLED")
        return _blocked(conn, p, response, cpe_id, str(exc.detail)[:60], body, view["id"])
    conn.execute(
        text("INSERT INTO ping_test_runs (tenant_id, cpe_id, job_id, target_id, requested_by) VALUES (:t, :c, :j, :g, :u)"),
        {"t": p.tenant_id, "c": cpe_id, "j": UUID(view["id"]), "g": body.target_id, "u": p.id})
    audit(conn, p, "ping.requested", "cpe", str(cpe_id), {"target_id": body.target_id, "job_id": view["id"]})
    return {"outcome": "submitted", "reason": None, "run": _run_by_job(conn, UUID(view["id"]))}
