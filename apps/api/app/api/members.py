"""Workspace members and the administrator-driven MFA reset.

MFA belongs to the ACCOUNT (users_global), not to a workspace, so an administrator of one workspace may only reset it for people who
belong to nobody else's workspace; anything wider is a platform decision. The reset is a sensitive action: the administrator
re-proves who they are (password AND a second factor, which therefore must be enabled for them), it is rate limited like a login,
every use is audited, and the target's refresh tokens are revoked so a stolen session does not outlive the reset.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import _client_ip, _gate, _record, _throttled, audit
from app.api.session import _check_second_factor, _mfa_required, _reauth
from app.core.db import get_engine, scoped_connection
from app.core.settings import Settings, get_settings
from app.events import outbox

router = APIRouter()


@router.get("/v1/members")
def list_members(p: Principal = Depends(require("members:read")), conn: Connection = TENANT_CONN,
                 settings: Settings = Depends(get_settings)) -> dict:
    rows = conn.execute(
        text(
            "SELECT m.user_id, u.email, u.display_name, m.role, COALESCE(mf.enabled, false) AS mfa_enabled "
            "FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id "
            "LEFT JOIN user_mfa mf ON mf.user_id = m.user_id "
            "WHERE m.tenant_id = :t AND u.is_active ORDER BY u.email"
        ),
        {"t": p.tenant_id},
    )
    return {
        "can_reset_mfa": p.can("members:mfa_reset"),
        "members": [{"user_id": str(r.user_id), "email": r.email, "display_name": r.display_name, "role": r.role,
                     "mfa_enabled": r.mfa_enabled, "is_self": r.user_id == p.id} for r in rows],
    }


class ResetIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=24)  # the administrator's own TOTP or recovery code


@router.post("/v1/members/{user_id}/mfa/reset")
def reset_member_mfa(
    user_id: UUID,
    body: ResetIn,
    request: Request,
    p: Principal = Depends(require("members:mfa_reset")),
    conn: Connection = TENANT_CONN,
    settings: Settings = Depends(get_settings),
) -> dict:
    if user_id == p.id:
        raise HTTPException(409, "use the account security page to change your own MFA")
    # Per-ACCOUNT lock (shared with every membership writer: app.cli add-member takes the same key). Held until this transaction ends, so
    # "belongs to no other workspace" stays true from the check below to the DELETE.
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"account:{user_id}"})
    member = conn.execute(
        text("SELECT 1 FROM tenant_memberships WHERE tenant_id = :t AND user_id = :u"), {"t": p.tenant_id, "u": user_id}
    ).first()
    if member is None:
        raise HTTPException(404, "member not found")
    with scoped_connection(get_engine(), user_id=user_id) as other:  # the target's own view: ALL of their memberships
        elsewhere = other.execute(
            text("SELECT count(*) FROM tenant_memberships WHERE user_id = :u AND tenant_id <> :t"), {"u": user_id, "t": p.tenant_id}
        ).scalar_one()
    if elsewhere:
        raise HTTPException(409, "this account also belongs to other workspaces; MFA is account-wide and must be reset by platform support")

    # Re-authentication in its OWN transaction: a failed attempt must stay recorded (throttle) even though the request then fails.
    key, ip = f"mfa-reset:{p.id}", _client_ip(request, settings)
    with scoped_connection(get_engine(), user_id=p.id) as auth:
        has_mfa = bool(auth.execute(text("SELECT enabled FROM user_mfa WHERE user_id = :u"), {"u": p.id}).scalar())
        if not has_mfa:
            outcome = "no_mfa"
        elif _gate(auth, key, ip):
            outcome = "locked"
        elif _reauth(auth, request, settings, p.id, body.password) is None:
            outcome = "bad"
        else:
            ok = _check_second_factor(auth, settings, p.id, body.code)
            _record(auth, key, ip, ok)
            outcome = "ok" if ok else "bad"
    if outcome == "no_mfa":
        raise HTTPException(409, "enable your own MFA before resetting someone else's")
    if outcome == "locked":
        raise _throttled()
    if outcome == "bad":
        raise HTTPException(401, "invalid credentials")

    conn.execute(text("SELECT 1 FROM user_mfa WHERE user_id = :u FOR UPDATE"), {"u": user_id})  # serialise with their own enrol/activate
    had = conn.execute(text("DELETE FROM user_mfa WHERE user_id = :u RETURNING enabled"), {"u": user_id}).first()
    conn.execute(text("DELETE FROM mfa_recovery_codes WHERE user_id = :u"), {"u": user_id})
    revoked = conn.execute(
        text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL RETURNING 1"), {"u": user_id}
    ).rowcount
    audit(conn, p, "member.mfa_reset", "user", str(user_id), {
        "had_mfa": bool(had and had.enabled), "revoked_sessions": revoked,
        "enrolment_now_required": _mfa_required(conn, settings, user_id)})
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="user", aggregate_id=user_id, event_type="member.mfa_reset",
                   payload={"by": str(p.id), "revoked_sessions": revoked})
    return {"status": "reset", "revoked_sessions": revoked}
