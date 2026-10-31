"""Authorizing ONE bench maneuver through the API (ADR-0031 section 2(e); owner decision 2026-10-30: operator role and up, no longer only the owner).

What it does NOT change: the maneuver still needs everything ADR-0030 asks for (tenant flag, bench target, registry entry, the job and its approval,
the signed envelope, the Edge's own checks). This only records the PRIOR single-use authorization, which until now only the owner CLI could. It is short
(5..120 min), bound to one operation + target + parameters hash, and the job engine refuses to use it for a job whose requester or approver is the person
who gave it. The only writer is the SQL function `app_bench_authorize`, executable only by the dedicated `fibercore_rbac` connection."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.api.deps import TENANT_CONN, Principal, require
from app.core import bench
from app.core.db import get_rbac_engine

router = APIRouter()

STATUS = {
    "role_cannot_authorize": 403, "target_not_bench": 409, "target_write_locked": 409, "bench_writes_disabled": 409, "authorization_already_open": 409,
    "authorization_not_found": 404, "authorization_not_open": 409, "owner_authorization": 403, "window_invalid": 422, "params_invalid": 422,
}


class AuthorizeIn(BaseModel):
    cpe_id: UUID
    operation: str = Field(min_length=1, max_length=40)
    params: dict = Field(default_factory=dict)
    minutes: int = Field(default=30, ge=5, le=120)


def _call(sql: str, args: dict) -> dict:
    engine = get_rbac_engine()
    if engine is None:
        raise HTTPException(503, "rbac_unavailable")   # fail closed: no dedicated connection, no API authorization
    try:
        with engine.begin() as c:
            return c.execute(text(sql), args).scalar_one()
    except DBAPIError as exc:
        state = str(getattr(exc.orig, "sqlstate", "") or "")
        code = str(getattr(getattr(exc.orig, "diag", None), "message_primary", "") or "")
        if state == "P0001" and code in STATUS:
            raise HTTPException(STATUS[code], code) from exc
        raise


@router.post("/v1/bench/authorizations", status_code=201)
def authorize(body: AuthorizeIn, p: Principal = Depends(require("bench:authorize"))) -> dict:
    if not bench.EDGE_SUPPORT:
        raise HTTPException(409, "edge_support_missing")
    if body.operation not in bench.BENCH_OPS:
        raise HTTPException(422, "operation outside the bench catalog")
    if not bench.params_valid(body.operation, body.params):
        raise HTTPException(422, "parameters outside the bench catalog")
    if body.operation in bench.SPEED_OPS and not bench.SPEED_EDGE_SUPPORT:
        raise HTTPException(409, "edge_support_missing")   # ADR-0038: the Edge half of the speed test is not delivered yet
    res = _call("SELECT app_bench_authorize(:a, :t, :c, :o, :h, :m)",
                {"a": p.id, "t": p.tenant_id, "c": body.cpe_id, "o": body.operation, "h": bench.params_hash(body.params), "m": body.minutes})
    return {"id": res["id"], "window_end": res["window_end"], "operation": body.operation, "minutes": body.minutes}


@router.delete("/v1/bench/authorizations/{authorization_id}")
def revoke(authorization_id: UUID, p: Principal = Depends(require("bench:authorize"))) -> dict:
    _call("SELECT app_bench_revoke(:a, :t, :i)", {"a": p.id, "t": p.tenant_id, "i": authorization_id})
    return {"status": "revoked"}


@router.get("/v1/bench/authorizations")
def list_authorizations(cpe_id: UUID | None = Query(None), limit: int = Query(20, ge=1, le=100),
                        p: Principal = Depends(require("jobs:read")), conn: Connection = TENANT_CONN) -> dict:
    """Authorizations of the bench targets, newest first. Who gave each one is shown by e-mail only to callers that also read members."""
    rows = conn.execute(
        text("SELECT a.id, a.operation, a.cpe_id, a.state, a.window_start, a.window_end, a.authorized_via, a.first_run, a.authorized_by_user_id, "
             "u.email, (a.state = 'open' AND now() < a.window_end AND now() >= a.window_start) AS live "
             "FROM bench_authorizations a LEFT JOIN users_global u ON u.id = a.authorized_by_user_id "
             "WHERE (CAST(:c AS uuid) IS NULL OR a.cpe_id = CAST(:c AS uuid)) ORDER BY a.created_at DESC LIMIT :l"),
        {"c": cpe_id, "l": limit})
    show = p.can("members:read")
    return {
        "can_authorize": p.can("bench:authorize"),
        "operations": [o for o in bench.BENCH_OPS if o in bench.BENCH_AUTHORIZERS.get(p.role, ())] if p.can("bench:authorize") else [],  # catalog order: the CPE ones first
        "items": [{"id": str(r.id), "operation": r.operation, "cpe_id": str(r.cpe_id), "state": r.state, "live": bool(r.live),
                   "window_start": r.window_start.isoformat(), "window_end": r.window_end.isoformat(), "via": r.authorized_via,
                   "mine": r.authorized_by_user_id == p.id, "by": r.email if show else None} for r in rows],
    }
