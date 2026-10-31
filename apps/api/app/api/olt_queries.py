"""Read-only queries of the OLT from its screen (ADR-0029): the cloud half of the `olt_query` job.

A request here is the existing job (preview, then submit), with the closed intent the job engine builds and checks. Nothing in this module reaches
equipment: while the tenant flag `olt_query` is off (or the channel is switched off in code, `olt_query.EDGE_SUPPORT`) every request is refused with `olt_query_disabled` and no job is created.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api import jobs
from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import features, olt_cache, olt_query

router = APIRouter()


def _olt_or_404(conn: Connection, olt_id: UUID) -> None:
    if conn.execute(text("SELECT 1 FROM olts WHERE id = :i"), {"i": olt_id}).first() is None:
        raise HTTPException(404, "olt not found")


@router.get("/v1/olts/{olt_id}/queries")
def list_queries(olt_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    """The catalog as this caller sees it: what each query takes, and whether it is offered now (and, if not, why)."""
    _olt_or_404(conn, olt_id)
    on = olt_query.EDGE_SUPPORT and features.enabled(conn, p.tenant_id, "olt_query")
    items = []
    for q in olt_query.CATALOG:
        if not (p.can("olt_query:run") and p.can("jobs:request") and p.can("jobs:read")):   # jobs:read: the person must be able to follow what they asked for
            reason = "not_permitted"
        elif q.id not in olt_query.ROLLOUT:
            reason = "query_not_enabled"
        elif not on:
            reason = "olt_query_disabled"
        else:
            reason = None
        items.append({"id": q.id, "title": q.title, "scope": q.scope, "fields": list(olt_query.SCOPE_FIELDS[q.scope]), "validated": q.validated,
                      "offered": reason is None, "reason": reason})
    return {"olt_id": str(olt_id), "catalog_version": olt_query.catalog_version(), "enabled": on,
            "limits": {"user_per_hour": olt_query.USER_PER_HOUR, "tenant_per_hour": olt_query.TENANT_PER_HOUR, **olt_query.LIMITS}, "items": items}


class QueryIn(BaseModel):
    params: dict = Field(default_factory=dict)
    refresh: bool = False   # ask the equipment even if a fresh value is cached (own quota)


def _scope_params(query_id: str, params: dict) -> dict:
    try:
        return olt_query.check_params(query_id, params)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/v1/olts/{olt_id}/queries/{query_id}/latest")
def latest_result(olt_id: UUID, query_id: str, slot: int | None = None, port: int | None = None, ont: int | None = None,
                  p: Principal = Depends(require("olt_query:run")), conn: Connection = TENANT_CONN) -> dict:
    """The last typed value of a query, with its age; a value older than its TTL says `stale` and is never presented as current. Reads the cache only."""
    if not p.can("inventory:read"):
        raise HTTPException(403, "forbidden")
    _olt_or_404(conn, olt_id)
    given = {k: v for k, v in (("slot", slot), ("port", port), ("ont", ont)) if v is not None}
    key = olt_cache.params_key(_scope_params(query_id, given))
    hit = olt_cache.latest(conn, olt_id, query_id, key)
    if hit is None:
        raise HTTPException(404, "no_cached_value")
    return {"olt_id": str(olt_id), "query_id": query_id, **hit}


@router.post("/v1/olts/{olt_id}/queries/{query_id}", status_code=200)
def request_query(
    olt_id: UUID, query_id: str, body: QueryIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    p: Principal = Depends(require("olt_query:run")), conn: Connection = TENANT_CONN,
) -> dict:
    if not (p.can("jobs:request") and p.can("jobs:read")):
        raise HTTPException(403, "forbidden")
    _olt_or_404(conn, olt_id)
    if "query_id" in body.params:
        raise HTTPException(422, "fields_do_not_match_scope")  # the query is the one in the path, for the intent and for the audit alike
    # cache first (ADR-0032): a fresh value answers without touching the equipment. Only under the SAME gates a job would face (flag, rollout, channel).
    if jobs._query_gate(conn, p.tenant_id, {"query_id": query_id}) is None and query_id in olt_query.BY_ID:
        key = olt_cache.params_key(_scope_params(query_id, body.params))
        hit = olt_cache.latest(conn, olt_id, query_id, key)
        if hit is not None and not hit["stale"] and not body.refresh:
            return {"outcome": "cached", "cached": hit}
        if body.refresh:
            used = conn.execute(text("SELECT count(*) FROM audit_log WHERE action = 'olt_query.refresh' AND target_id = :o AND created_at > now() - interval '1 hour'"), {"o": str(olt_id)}).scalar()
            if used >= olt_cache.REFRESH_PER_HOUR:
                raise HTTPException(429, "olt_query_refresh_quota")
    view = jobs.preview(jobs.PreviewIn(operation="olt_query", target_id=olt_id, params={"query_id": query_id, **body.params}), idempotency_key, p, conn)
    if view["status"] != "PREVIEWED":  # the same request again: nothing new is created
        return {"outcome": "existing", "job": view}
    view = jobs.submit(UUID(view["id"]), p, conn)
    audit(conn, p, "olt_query.requested", "olt", str(olt_id), {"query_id": query_id, "job_id": view["id"]})
    if body.refresh:
        audit(conn, p, "olt_query.refresh", "olt", str(olt_id), {"query_id": query_id})
    return {"outcome": "submitted", "job": view}
