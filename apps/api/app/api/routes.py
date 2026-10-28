from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Connection, text

from app import __version__
from app.api.deps import Principal, get_principal, require, tenant_conn
from app.core.db import get_engine, scoped_connection
from app.core.modules import Infra, evaluate, load_manifest, probe_nats, probe_postgres
from app.core.security import decode_token, issue_token, verify_secret
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
MAX_FAILURES = 5
LOCK_WINDOW = "15 minutes"


def _locked(conn: Connection, key: str) -> bool:
    """Lock after MAX_FAILURES failures since the last success within LOCK_WINDOW (applies even if the next password is right)."""
    n = conn.execute(
        text(
            "SELECT count(*) FROM login_attempts WHERE key = :k AND NOT success AND created_at > now() - CAST(:w AS interval) "
            "AND created_at > COALESCE((SELECT max(created_at) FROM login_attempts WHERE key = :k AND success), '-infinity')"
        ),
        {"k": key, "w": LOCK_WINDOW},
    ).scalar_one()
    return n >= MAX_FAILURES


def _record(key: str, success: bool) -> None:
    with scoped_connection(get_engine()) as conn:  # own transaction: failures must persist even when the request errors out
        conn.execute(text("INSERT INTO login_attempts (key, success) VALUES (:k, :s)"), {"k": key, "s": success})


def _throttled() -> HTTPException:
    return HTTPException(429, "too many failed attempts; try again later", headers={"Retry-After": "900"})

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
    key = body.email.lower()
    with scoped_connection(get_engine()) as conn:
        if _locked(conn, key):
            raise _throttled()
        row = conn.execute(
            text("SELECT id, password_hash, is_active FROM users_global WHERE lower(email) = lower(:e)"),
            {"e": body.email},
        ).first()
    ok = verify_secret(row.password_hash if row else None, body.password)
    if not (row and row.is_active and ok):
        _record(key, False)  # unknown accounts are recorded too: no user enumeration through lockout behaviour
        raise HTTPException(401, "invalid credentials")
    _record(key, True)
    return TokenOut(access_token=issue_token(settings, sub=row.id, kind="user"), expires_in=settings.jwt_ttl_seconds)


@router.post("/v1/auth/service-token", response_model=TokenOut)
def service_login(body: ServiceLoginIn, settings: Settings = Depends(get_settings)) -> TokenOut:
    key = f"svc:{body.client_id}"
    with scoped_connection(get_engine(), user_id=body.client_id) as conn:
        if _locked(conn, key):
            raise _throttled()
        row = conn.execute(
            text("SELECT id, tenant_id, secret_hash, is_active FROM service_accounts WHERE id = :i"),
            {"i": body.client_id},
        ).first()
    ok = verify_secret(row.secret_hash if row else None, body.client_secret)
    if not (row and row.is_active and ok):
        _record(key, False)
        raise HTTPException(401, "invalid credentials")
    _record(key, True)
    return TokenOut(
        access_token=issue_token(settings, sub=row.id, kind="service", tenant_id=row.tenant_id),
        expires_in=settings.jwt_ttl_seconds,
    )


@router.get("/v1/auth/workspaces")
def my_workspaces(
    request: Request, authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> list[dict]:
    """Workspaces (tenants) the authenticated USER belongs to; needs no tenant selection. Service tokens: not applicable."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(settings, authorization[7:].strip())
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(401, "invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"}) from exc
    if claims.kind != "user":
        raise HTTPException(403, "users only")
    with scoped_connection(get_engine(), user_id=claims.sub) as conn:
        if not conn.execute(text("SELECT is_active FROM users_global WHERE id = :u"), {"u": claims.sub}).scalar():
            raise HTTPException(401, "invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"})  # revoked accounts
        rows = conn.execute(
            text("SELECT t.id, t.name, m.role FROM tenant_memberships m JOIN tenants t ON t.id = m.tenant_id "
                 "WHERE m.user_id = :u AND t.status = 'active' ORDER BY t.name"),
            {"u": claims.sub},
        )
        return [{"tenant_id": str(r.id), "name": r.name, "role": r.role} for r in rows]


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
    if body.tenant_id != p.tenant_id or p.edge_id is None or body.edge_id != p.edge_id:
        raise HTTPException(403, "token is not bound to this edge")  # one credential <-> one edge
    res = conn.execute(
        text(
            "UPDATE edges SET version = :v, last_heartbeat_at = now() "
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
        # Derived at read time from heartbeat age; only 'revoked' is stored (owner-set).
        if r.status == "revoked":
            status = "revoked"
        elif r.last_heartbeat_at is None:
            status = "unknown"
        else:
            status = "online" if now - r.last_heartbeat_at <= EDGE_OFFLINE_AFTER else "offline"
        out.append({"id": str(r.id), "name": r.name, "site_name": r.site_name, "version": r.version,
                    "last_heartbeat_at": r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None, "status": status})
    return out
