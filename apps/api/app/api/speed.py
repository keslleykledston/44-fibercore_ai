"""Speed Diagnostics TR-143, cloud half (ADR-0038).

This adds NO way to write to equipment. A request here is exactly the job the engine already knows (preview, then submit) for the two bench operations
`speed_test_download` / `speed_test_upload`; everything after it is unchanged: the global gate (HOMOLOGATED_WRITES stays empty), the bench gate (bench target,
registry evidence, the owner's prior single-use authorization), another person's approval, the signed envelope and the Edge's own refusals. What this layer
adds is the screen's contract (what this CPE can do, with which logical endpoints), the PON-protecting limits, and the run history with the figures the
cloud computed. The whole router answers 403 `feature_disabled` while the tenant flag `speed_diagnostics` is off.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api import jobs
from app.api.deps import TENANT_CONN, Principal, require
from app.api.inventory import _capabilities
from app.api.routes import audit
from app.core import bench, features, speed

router = APIRouter()

# the screen's single status word per run, from the job's lifecycle unless the cloud already computed an outcome
_JOB_STATUS = {"PENDING_APPROVAL": "awaiting_approval", "APPROVED": "queued", "DISPATCHED": "collecting", "ACCEPTED": "collecting",
               "DEVICE_PENDING": "collecting", "VERIFYING": "collecting", "CANCELLED": "cancelled", "EXPIRED": "expired",
               "FAILED": "failed", "UNKNOWN": "unknown", "SUCCEEDED": "unknown", "PREVIEWED": "queued"}

RUN_COLS = ("r.id, r.cpe_id, r.job_id, r.group_id, r.direction, r.endpoint_id, r.profile, r.created_at, r.outcome, r.mbps, r.bytes, r.duration_ms, "
            "r.reason, r.basis, r.completed_at, j.status AS job_status, j.result AS job_result")


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "speed_diagnostics")


def _run_view(r) -> dict:
    status = r.outcome or _JOB_STATUS.get(r.job_status, "unknown")
    detail = (r.job_result or {}).get("detail") if r.job_status in ("FAILED", "UNKNOWN") and isinstance(r.job_result, dict) else None
    return {
        "id": str(r.id), "cpe_id": str(r.cpe_id), "job_id": str(r.job_id), "group_id": str(r.group_id), "direction": r.direction,
        "endpoint_id": r.endpoint_id, "profile": r.profile, "status": status, "created_at": r.created_at.isoformat(),
        # the figure exists only for a measurement; `null` is shown as "—", never as 0
        "mbps": float(r.mbps) if r.mbps is not None else None, "bytes": r.bytes, "duration_ms": r.duration_ms,
        "reliable": r.outcome == "completed", "reason": r.reason or (str(detail)[:60] if detail else None), "basis": r.basis,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }


def _cpe_or_404(conn: Connection, cpe_id: UUID):
    c = conn.execute(text("SELECT id, vendor, model, firmware FROM cpes WHERE id = :i"), {"i": cpe_id}).first()
    if c is None:
        raise HTTPException(404, "cpe not found")
    return c


def _endpoints(conn: Connection) -> list[dict]:
    rows = conn.execute(text("SELECT id, label, target_kind, region, enabled, health, health_at FROM speed_endpoints ORDER BY target_kind, id")).all()
    return [{"id": r.id, "label": r.label, "target_kind": r.target_kind, "region": r.region, "enabled": r.enabled, "health": r.health,
             "health_at": r.health_at.isoformat() if r.health_at else None, "ready": r.enabled and r.health == "ok"} for r in rows]


def _direction_state(p: Principal, caps: list[dict], operation: str, is_bench: bool, redirect_ok: bool) -> dict:
    """Why this direction can or cannot be requested right now, in the ORDER a person can act on it. Same decision the request applies (it re-checks)."""
    entry = next((c for c in caps if c["name"] == operation and c["protocol"] == "tr069"), None)
    reason = None
    if not (p.can("diagnostics:speed_run") and p.can("jobs:request")):
        reason = "not_permitted"
    elif not is_bench:
        reason = "operation_not_homologated"   # every CPE outside the bench list: the global gate (HOMOLOGATED_WRITES) stays empty
    elif entry is None or entry["status"] != "supported" or entry["certification"] not in ("observed", "certified"):
        reason = "capability_not_observed"
    elif not redirect_ok:
        reason = "redirect_unverified"
    return {"operation": operation, "offered": reason is None, "reason": reason,
            "certification": entry["certification"] if entry else "identified", "status": entry["status"] if entry else "unknown"}


@router.get("/v1/cpes/{cpe_id}/speed/capabilities")
def capabilities(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    c = _cpe_or_404(conn, cpe_id)
    caps = _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware)
    is_bench = bool(conn.execute(text("SELECT 1 FROM bench_targets WHERE cpe_id = :c"), {"c": cpe_id}).first())
    redirect_ok = bool(c.vendor and c.model and c.firmware and speed.redirect_verified(conn, p.tenant_id, c.vendor, c.model, c.firmware))
    eps = _endpoints(conn)
    directions = {d: _direction_state(p, caps, op, is_bench, redirect_ok) for d, op in speed.DIRECTIONS.items()}
    return {
        "cpe_id": str(cpe_id), "bench_target": is_bench, "redirect_verified": redirect_ok, "edge_support": bench.SPEED_EDGE_SUPPORT,
        "directions": directions, "endpoints": eps, "profiles": list(bench.SPEED_PROFILES),
        "limits": {"per_cpe": speed.LIMIT_PER_CPE, "per_pon": speed.LIMIT_PER_PON, "per_tenant": speed.LIMIT_PER_TENANT},
        # without an endpoint that is enabled and healthy there is nothing to test against: the screen says so instead of offering a button
        "ready": bench.SPEED_EDGE_SUPPORT and any(d["offered"] for d in directions.values()) and any(e["ready"] for e in eps),
    }


@router.get("/v1/speed/health")
def health(p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    return {"endpoints": _endpoints(conn), "edge_support": bench.SPEED_EDGE_SUPPORT}


@router.get("/v1/cpes/{cpe_id}/speed/runs")
def list_runs(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    _cpe_or_404(conn, cpe_id)
    rows = conn.execute(
        text(f"SELECT {RUN_COLS} FROM speed_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id "  # noqa: S608
             "WHERE r.cpe_id = :c ORDER BY r.created_at DESC LIMIT 20"), {"c": cpe_id}).all()
    return {"cpe_id": str(cpe_id), "items": [_run_view(r) for r in rows]}


@router.get("/v1/cpes/{cpe_id}/speed/runs/{run_id}")
def get_run(cpe_id: UUID, run_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(
        text(f"SELECT {RUN_COLS} FROM speed_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id "  # noqa: S608
             "WHERE r.id = :i AND r.cpe_id = :c"), {"i": run_id, "c": cpe_id}).first()
    if r is None:
        raise HTTPException(404, "run not found")
    return _run_view(r)


class RunIn(BaseModel):
    direction: str = Field(pattern=r"^(download|upload)$")
    endpoint_id: str = Field(min_length=2, max_length=31, pattern=r"^[a-z0-9][a-z0-9-]{1,30}$")
    profile: str = Field(pattern=r"^(10mb|50mb|200mb)$")
    group_id: UUID | None = None   # the second direction of the same test joins the first one's group


def _blocked(conn: Connection, p: Principal, response: Response, cpe_id: UUID, reason: str, body: RunIn, job_id: str | None = None) -> dict:
    """A refusal is an answer with a status and an audit row, not an exception: the transaction commits so the refusal stays on record."""
    audit(conn, p, "speed.blocked", "cpe", str(cpe_id),
          {"direction": body.direction, "endpoint_id": body.endpoint_id, "profile": body.profile, "reason": reason, **({"job_id": job_id} if job_id else {})})
    response.status_code = 409
    return {"outcome": "blocked", "reason": reason, "run": None}


@router.post("/v1/cpes/{cpe_id}/speed/runs", status_code=201)
def request_run(
    cpe_id: UUID, body: RunIn, response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    p: Principal = Depends(require("diagnostics:speed_run")), conn: Connection = TENANT_CONN,
) -> dict:
    _flag(conn, p)
    if not p.can("jobs:request"):
        raise HTTPException(403, "forbidden")
    c = _cpe_or_404(conn, cpe_id)
    operation = speed.DIRECTIONS[body.direction]
    params = {"target": body.endpoint_id, "profile": body.profile}
    # the same key arriving twice at once: the second waits here for the first to COMMIT and then finds its run, instead of reaching the slot check first and
    # being refused as busy by the very run it is a retry of (the engine takes the same lock again, which is harmless; order is always key -> slots)
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"job-idempotency|{p.tenant_id}|{idempotency_key}"})
    # the same key again (a lost answer, a double click) returns what it created; a key reused for a different test is the engine's own 409
    if conn.execute(text("SELECT 1 FROM jobs WHERE idempotency_key = :k"), {"k": idempotency_key}).first():
        view = jobs.create_preview(jobs.PreviewIn(operation=operation, target_id=cpe_id, params=params), idempotency_key, p, conn)
        run = _run_by_job(conn, UUID(view["id"]))
        response.status_code = 200
        return {"outcome": "existing", "reason": None if run else "cancelled", "run": run}
    group = body.group_id or None
    if group is not None:
        # a group is ONE test: at most one run per direction, all for the same CPE, endpoint and profile (the unique index backs this under concurrency)
        members = conn.execute(text("SELECT cpe_id, endpoint_id, profile, direction FROM speed_test_runs WHERE group_id = :g"), {"g": group}).all()
        if not members or any(m.cpe_id != cpe_id or m.endpoint_id != body.endpoint_id or m.profile != body.profile or m.direction == body.direction for m in members):
            return _blocked(conn, p, response, cpe_id, "group_mismatch", body)
    caps = _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware)
    is_bench = bool(conn.execute(text("SELECT 1 FROM bench_targets WHERE cpe_id = :c"), {"c": cpe_id}).first())
    redirect_ok = bool(c.vendor and c.model and c.firmware and speed.redirect_verified(conn, p.tenant_id, c.vendor, c.model, c.firmware))
    st = _direction_state(p, caps, operation, is_bench, redirect_ok)
    if not st["offered"]:
        return _blocked(conn, p, response, cpe_id, st["reason"], body)
    ep = conn.execute(text("SELECT enabled, health FROM speed_endpoints WHERE id = :i"), {"i": body.endpoint_id}).first()
    if ep is None or not ep.enabled:
        return _blocked(conn, p, response, cpe_id, "endpoint_unavailable", body)
    if ep.health != "ok":
        return _blocked(conn, p, response, cpe_id, "endpoint_unhealthy", body)
    pon = speed.pon_of(conn, p.tenant_id, cpe_id)
    if pon is None:
        return _blocked(conn, p, response, cpe_id, "pon_unknown", body)   # no confirmed ONU<->CPE link: the PON limit cannot be honoured, so nothing runs
    busy = speed.busy_reason(conn, p.tenant_id, cpe_id, pon)   # takes the per-tenant slot lock, held to the end of this transaction
    if busy:
        return _blocked(conn, p, response, cpe_id, busy, body)
    view = jobs.create_preview(jobs.PreviewIn(operation=operation, target_id=cpe_id, params=params), idempotency_key, p, conn)
    try:
        view = jobs.submit(UUID(view["id"]), p, conn)
    except HTTPException as exc:   # the write gate (or anything the engine refuses): the request ends here, visibly, and leaves no live job
        jobs.cas(conn, UUID(view["id"]), "CANCELLED")
        return _blocked(conn, p, response, cpe_id, str(exc.detail)[:60], body, view["id"])
    conn.execute(
        text("INSERT INTO speed_test_runs (tenant_id, cpe_id, job_id, group_id, direction, endpoint_id, profile, pon_id, requested_by) "
             "VALUES (:t, :c, :j, COALESCE(:g, gen_random_uuid()), :d, :e, :f, :p, :u)"),
        {"t": p.tenant_id, "c": cpe_id, "j": UUID(view["id"]), "g": group, "d": body.direction, "e": body.endpoint_id, "f": body.profile, "p": pon, "u": p.id})
    audit(conn, p, "speed.requested", "cpe", str(cpe_id),
          {"direction": body.direction, "endpoint_id": body.endpoint_id, "profile": body.profile, "job_id": view["id"]})
    return {"outcome": "submitted", "reason": None, "run": _run_by_job(conn, UUID(view["id"]))}


def _run_by_job(conn: Connection, job_id: UUID) -> dict | None:
    r = conn.execute(
        text(f"SELECT {RUN_COLS} FROM speed_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id WHERE r.job_id = :j"),  # noqa: S608
        {"j": job_id}).first()
    return _run_view(r) if r else None
