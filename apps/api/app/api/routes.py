from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Connection, text

from app import __version__
from app.api.deps import Principal, get_principal, require, tenant_conn
from app.core.db import get_engine, scoped_connection
from app.core.modules import Infra, evaluate, load_manifest, probe_nats, probe_postgres
from app.core.security import issue_token, verify_secret
from app.core.settings import Settings, get_settings

router = APIRouter()


def audit(conn: Connection, p: Principal, action: str, target_type: str, target_id: str, evidence: dict | None = None):
    conn.execute(
        text(
            "INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted) "
            "VALUES (:t, :a, :act, :tt, :ti, CAST(:e AS jsonb))"
        ),
        {"t": p.tenant_id, "a": p.id, "act": action, "tt": target_type, "ti": target_id, "e": json.dumps(evidence or {})},
    )


# ---- platform (unauthenticated, no sensitive data) -------------------------------------------
@router.get("/livez")
def livez() -> dict:
    return {"status": "alive", "service": "api-core"}


@router.get("/readyz")
def readyz() -> dict:
    from fastapi.responses import JSONResponse

    try:
        ok = probe_postgres(get_engine())
    except RuntimeError:
        ok = False
    if not ok:
        return JSONResponse({"status": "not_ready", "reason": "postgres unavailable"}, status_code=503)
    return {"status": "ready", "service": "api-core"}


@router.get("/version")
def version(settings: Settings = Depends(get_settings)) -> dict:
    return {"service": "api-core", "version": __version__, "environment": settings.environment}


# ---- auth ------------------------------------------------------------------------------------
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class ServiceLoginIn(BaseModel):
    client_id: UUID
    client_secret: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


@router.post("/v1/auth/token", response_model=TokenOut)
def login(body: LoginIn, settings: Settings = Depends(get_settings)) -> TokenOut:
    with scoped_connection(get_engine()) as conn:
        row = conn.execute(
            text("SELECT id, password_hash, is_active FROM users_global WHERE lower(email) = lower(:e)"),
            {"e": body.email},
        ).first()
    ok = verify_secret(row.password_hash if row else None, body.password)
    if not (row and row.is_active and ok):
        raise HTTPException(401, "invalid credentials")
    return TokenOut(access_token=issue_token(settings, sub=row.id, kind="user"), expires_in=settings.jwt_ttl_seconds)


@router.post("/v1/auth/service-token", response_model=TokenOut)
def service_login(body: ServiceLoginIn, settings: Settings = Depends(get_settings)) -> TokenOut:
    with scoped_connection(get_engine(), user_id=body.client_id) as conn:
        row = conn.execute(
            text("SELECT id, tenant_id, secret_hash, is_active FROM service_accounts WHERE id = :i"),
            {"i": body.client_id},
        ).first()
    ok = verify_secret(row.secret_hash if row else None, body.client_secret)
    if not (row and row.is_active and ok):
        raise HTTPException(401, "invalid credentials")
    return TokenOut(
        access_token=issue_token(settings, sub=row.id, kind="service", tenant_id=row.tenant_id),
        expires_in=settings.jwt_ttl_seconds,
    )


@router.get("/v1/auth/me")
def me(p: Principal = Depends(get_principal)) -> dict:
    return {"id": str(p.id), "kind": p.kind, "tenant_id": str(p.tenant_id), "role": p.role}


# ---- tenant-scoped ---------------------------------------------------------------------------
@router.get("/v1/tenant")
def current_tenant(p: Principal = Depends(require("tenant:read")), conn: Connection = Depends(tenant_conn)) -> dict:
    row = conn.execute(text("SELECT id, name, status, created_at FROM tenants")).first()  # RLS scopes
    if not row:
        raise HTTPException(404, "tenant not found")
    audit(conn, p, "tenant.read", "tenant", str(row.id))
    return {"id": str(row.id), "name": row.name, "status": row.status, "created_at": row.created_at.isoformat()}


@router.get("/v1/audit")
def list_audit(
    limit: int = Query(50, ge=1, le=200),
    p: Principal = Depends(require("audit:read")),
    conn: Connection = Depends(tenant_conn),
) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, actor_id, action, target_type, target_id, created_at FROM audit_log "
            "ORDER BY created_at DESC LIMIT :l"
        ),
        {"l": limit},
    )
    return [
        {"id": str(r.id), "actor_id": str(r.actor_id) if r.actor_id else None, "action": r.action,
         "target_type": r.target_type, "target_id": r.target_id, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@router.get("/v1/platform/modules")
def modules(_: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> list[dict]:
    try:
        engine = get_engine()
    except RuntimeError:
        engine = None
    infra = Infra(postgres=probe_postgres(engine), nats=probe_nats(settings.nats_monitor_url))
    return evaluate(load_manifest(settings.module_manifest), infra)


@router.get("/v1/platform/versions")
def versions(_: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> list[dict]:
    items = [{"module": "api-core", "version": __version__}]
    items += [{"module": m["id"], "version": m["version"]} for m in load_manifest(settings.module_manifest)]
    return items


# ---- edge fleet -------------------------------------------------------------------------------
EDGE_OFFLINE_AFTER = timedelta(seconds=90)


class EdgeHeartbeat(BaseModel):
    edge_id: UUID
    tenant_id: UUID
    version: str = Field(min_length=1, max_length=64)
    sent_at: datetime


@router.post("/v1/edge/heartbeat", status_code=204)
def edge_heartbeat(
    body: EdgeHeartbeat,
    p: Principal = Depends(require("edge:heartbeat")),
    conn: Connection = Depends(tenant_conn),
) -> None:
    """Interim auth: Edge service-account bearer (role edge_agent). Target: mTLS identity (ADR-0011)."""
    if body.tenant_id != p.tenant_id:
        raise HTTPException(403, "tenant mismatch")
    res = conn.execute(
        text(
            "UPDATE edges SET version = :v, last_heartbeat_at = now(), status = 'online' "
            "WHERE id = :e AND tenant_id = :t AND status <> 'revoked'"
        ),
        {"v": body.version, "e": body.edge_id, "t": p.tenant_id},
    )
    if res.rowcount == 0:
        raise HTTPException(404, "edge not found")


@router.get("/v1/edges")
def list_edges(p: Principal = Depends(require("edge:read")), conn: Connection = Depends(tenant_conn)) -> list[dict]:
    now = datetime.now(UTC)
    out = []
    for r in conn.execute(text("SELECT id, name, site_name, version, last_heartbeat_at, status FROM edges ORDER BY name")):
        status = r.status
        if status == "online" and (r.last_heartbeat_at is None or now - r.last_heartbeat_at > EDGE_OFFLINE_AFTER):
            status = "offline"  # computed at read time: stale heartbeat never reads as online
        out.append({"id": str(r.id), "name": r.name, "site_name": r.site_name, "version": r.version,
                    "last_heartbeat_at": r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None, "status": status})
    return out
