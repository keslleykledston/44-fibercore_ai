"""Temporary access of the platform's support staff to a workspace (ADR-0031, section 5).

The workspace's own administrator grants it, for a stated reason and at most 8 hours; it can be revoked at any moment; every grant and revocation is
audited and visible to the workspace. It is only ever offered to accounts the platform itself marked as operators (CLI `platform-operator`), so the
administrator cannot hand the workspace to an arbitrary account. The delegate resolves as `platform_support` (tenant:read only, no personal data)
for as long as an unrevoked, unexpired row exists: `get_principal` asks the database on every request (see app/core/memberships.py).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.events import outbox

router = APIRouter()

MAX_HOURS = 8


class DelegationIn(BaseModel):
    email: EmailStr
    reason: str = Field(min_length=10, max_length=300)
    hours: int = Field(default=MAX_HOURS, ge=1, le=MAX_HOURS)


@router.get("/v1/platform-delegations")
def list_delegations(limit: int = Query(30, ge=1, le=100), p: Principal = Depends(require("members:read")),
                     conn: Connection = TENANT_CONN) -> dict:
    rows = conn.execute(
        text(
            "SELECT d.id, d.reason, d.created_at, d.expires_at, d.revoked_at, u.email AS delegate_email, u.display_name AS delegate_name, "
            "g.email AS granted_by_email, "
            "CASE WHEN d.revoked_at IS NOT NULL THEN 'revoked' WHEN clock_timestamp() >= d.expires_at THEN 'expired' ELSE 'active' END AS status "
            "FROM membership_delegations d JOIN users_global u ON u.id = d.user_id JOIN users_global g ON g.id = d.granted_by "
            "WHERE d.tenant_id = :t ORDER BY d.created_at DESC LIMIT :l"
        ),
        {"t": p.tenant_id, "l": limit},
    )
    return {
        "can_delegate": p.can("platform:delegate"),
        "max_hours": MAX_HOURS,
        "items": [{"id": str(r.id), "delegate_email": r.delegate_email, "delegate_name": r.delegate_name, "granted_by_email": r.granted_by_email,
                   "reason": r.reason, "created_at": r.created_at.isoformat(), "expires_at": r.expires_at.isoformat(),
                   "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None, "status": r.status} for r in rows],
    }


@router.post("/v1/platform-delegations", status_code=201)
def grant_delegation(body: DelegationIn, p: Principal = Depends(require("platform:delegate")), conn: Connection = TENANT_CONN) -> dict:
    target = conn.execute(
        text("SELECT id FROM users_global WHERE lower(email) = lower(:e) AND is_active AND is_platform_operator"), {"e": str(body.email)}
    ).scalar()
    if target is None:
        raise HTTPException(404, "operator_not_found")  # the same answer for "no such account", "inactive" and "not a platform operator"
    if target == p.id:
        raise HTTPException(422, "cannot_delegate_to_self")
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"delegation:{p.tenant_id}:{target}"})
    if conn.execute(text("SELECT 1 FROM tenant_memberships WHERE tenant_id = :t AND user_id = :u"), {"t": p.tenant_id, "u": target}).first():
        raise HTTPException(409, "already_member")  # a real member needs no delegation, and a delegation must never shadow a membership
    # renewing = a new reason and a new deadline; the previous delegation of the same person ends at the same instant, so one is active at a time
    replaced = conn.execute(
        text("UPDATE membership_delegations SET revoked_at = clock_timestamp(), revoked_by = :a "
             "WHERE tenant_id = :t AND user_id = :u AND revoked_at IS NULL RETURNING 1"),
        {"a": p.id, "t": p.tenant_id, "u": target},
    ).rowcount
    row = conn.execute(
        text("INSERT INTO membership_delegations (tenant_id, user_id, granted_by, reason, expires_at) "
             "VALUES (:t, :u, :a, btrim(:r), now() + make_interval(hours => :h)) RETURNING id, expires_at"),
        {"t": p.tenant_id, "u": target, "a": p.id, "r": body.reason, "h": body.hours},
    ).one()
    audit(conn, p, "platform.delegation_grant", "user", str(target),
          {"delegation_id": str(row.id), "reason": body.reason.strip(), "hours": body.hours, "replaced": replaced})
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="user", aggregate_id=target, event_type="platform.delegation_grant",
                   payload={"by": str(p.id), "delegation_id": str(row.id), "expires_at": row.expires_at.isoformat()})
    return {"id": str(row.id), "expires_at": row.expires_at.isoformat(), "replaced": replaced}


@router.delete("/v1/platform-delegations/{delegation_id}")
def revoke_delegation(delegation_id: UUID, p: Principal = Depends(require("platform:delegate")), conn: Connection = TENANT_CONN) -> dict:
    d = conn.execute(text("SELECT user_id FROM membership_delegations WHERE id = :i AND tenant_id = :t"), {"i": delegation_id, "t": p.tenant_id}).first()
    if d is None:
        raise HTTPException(404, "delegation_not_found")
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"delegation:{p.tenant_id}:{d.user_id}"})
    # every live delegation of that person ends, not just the one named: revoking must never leave a sibling working
    n = conn.execute(
        text("UPDATE membership_delegations SET revoked_at = clock_timestamp(), revoked_by = :a "
             "WHERE tenant_id = :t AND user_id = :u AND revoked_at IS NULL AND clock_timestamp() < expires_at RETURNING 1"),
        {"a": p.id, "t": p.tenant_id, "u": d.user_id},
    ).rowcount
    if n == 0:
        raise HTTPException(409, "delegation_not_active")
    audit(conn, p, "platform.delegation_revoke", "user", str(d.user_id), {"delegation_id": str(delegation_id), "revoked": n})
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="user", aggregate_id=d.user_id, event_type="platform.delegation_revoke",
                   payload={"by": str(p.id), "delegation_id": str(delegation_id)})
    return {"status": "revoked", "revoked": n}
