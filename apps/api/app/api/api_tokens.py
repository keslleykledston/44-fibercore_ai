"""API tokens of the organization (ADR-0051 D1): read-only integrations that are not a person.

An administrator creates a token (name, permissions from the CLOSED read-only list, up to 365 days); the secret is shown ONCE, only its SHA-256 is stored. The token authenticates as itself
(`Authorization: Bearer fcat_...`, see `deps._api_token_principal`), holds exactly the permissions it was given, is rate limited on its own bucket, stops with the organization's suspension and
can be revoked at any time. It cannot manage tokens, people, policies or anything outside the list, and nothing it does writes (the list holds only read permissions).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import api_tokens
from app.events import outbox

router = APIRouter()


class TokenIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    permissions: list[str] = Field(min_length=1, max_length=len(api_tokens.API_TOKEN_PERMISSIONS))
    days: int = Field(default=90, ge=1, le=api_tokens.MAX_DAYS)


def _view(r) -> dict:
    return {"id": str(r.id), "name": r.name, "prefix": r.prefix, "permissions": list(r.permissions), "created_at": r.created_at.isoformat(), "expires_at": r.expires_at.isoformat(),
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None, "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
            "state": "revoked" if r.revoked_at else ("expired" if r.expires_at <= datetime.now(UTC) else "active")}


@router.get("/v1/api-tokens")
def list_tokens(p: Principal = Depends(require("tokens:manage")), conn: Connection = TENANT_CONN) -> dict:
    rows = conn.execute(text("SELECT id, name, prefix, permissions, created_at, expires_at, last_used_at, revoked_at FROM api_tokens ORDER BY created_at DESC LIMIT 200")).all()
    return {"items": [_view(r) for r in rows], "allowed_permissions": list(api_tokens.API_TOKEN_PERMISSIONS), "max_active": api_tokens.MAX_ACTIVE_PER_ORGANIZATION, "max_days": api_tokens.MAX_DAYS}


@router.post("/v1/api-tokens", status_code=201)
def create_token(body: TokenIn, p: Principal = Depends(require("tokens:manage")), conn: Connection = TENANT_CONN) -> dict:
    """Returns the token ONCE. The permissions must all be in the closed read-only list."""
    perms = sorted(set(body.permissions))
    if any(x not in api_tokens.API_TOKEN_PERMISSIONS for x in perms):
        raise HTTPException(422, "permission_not_allowed")
    name = " ".join(body.name.split())
    if len(name) < 2:
        raise HTTPException(422, "name_invalid")
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"api-tokens:{p.tenant_id}"})
    active = conn.execute(text("SELECT count(*) FROM api_tokens WHERE revoked_at IS NULL AND expires_at > now()")).scalar_one()
    if active >= api_tokens.MAX_ACTIVE_PER_ORGANIZATION:
        raise HTTPException(409, "token_limit")
    token, prefix, digest = api_tokens.new_token()
    expires = datetime.now(UTC) + timedelta(days=body.days)
    tid = conn.execute(
        text("INSERT INTO api_tokens (tenant_id, name, prefix, token_hash, permissions, created_by, expires_at) VALUES (:t, :n, :p, :h, :perm, :u, :e) RETURNING id"),
        {"t": p.tenant_id, "n": name, "p": prefix, "h": digest, "perm": perms, "u": p.id, "e": expires}).scalar_one()
    audit(conn, p, "api_token.created", "api_token", str(tid), {"name": name, "prefix": prefix, "permissions": perms, "days": body.days})   # the audit trail NEVER holds the token
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="api_token", aggregate_id=tid, event_type="api_token.created", payload={"by": str(p.id)})
    return {"id": str(tid), "name": name, "prefix": prefix, "permissions": perms, "expires_at": expires.isoformat(), "token": token}


@router.delete("/v1/api-tokens/{token_id}")
def revoke_token(token_id: UUID, p: Principal = Depends(require("tokens:manage")), conn: Connection = TENANT_CONN) -> dict:
    row = conn.execute(text("UPDATE api_tokens SET revoked_at = now(), revoked_by = :u WHERE id = :i AND revoked_at IS NULL RETURNING name, prefix"), {"u": p.id, "i": token_id}).first()
    if row is None:
        raise HTTPException(404, "token_not_found")   # unknown, or already revoked: the same answer
    audit(conn, p, "api_token.revoked", "api_token", str(token_id), {"name": row.name, "prefix": row.prefix})
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="api_token", aggregate_id=token_id, event_type="api_token.revoked", payload={"by": str(p.id)})
    return {"revoked": True}
