"""Workspace members and the administrator-driven MFA reset.

MFA belongs to the ACCOUNT (users_global), not to a workspace, so an administrator of one workspace may only reset it for people who
belong to nobody else's workspace; anything wider is a platform decision. The reset is a sensitive action: the administrator
re-proves who they are (password AND a second factor, which therefore must be enabled for them), it is rate limited like a login,
every use is audited, and the target's refresh tokens are revoked so a stolen session does not outlive the reset.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import _client_ip, _gate, _record, _throttled, audit
from app.api.session import _check_second_factor, _mfa_required, _reauth
from app.core import role_policy
from app.core.db import get_engine, get_rbac_engine, scoped_connection
from app.core.permissions import CATALOG
from app.core.security import ROLE_PERMISSIONS
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
        "can_manage_roles": p.can("members:manage"),
        "members": [{"user_id": str(r.user_id), "email": r.email, "display_name": r.display_name, "role": r.role,
                     "mfa_enabled": r.mfa_enabled, "is_self": r.user_id == p.id,
                     "can_change_role": p.can("members:manage") and role_policy.can_change_any(p.role, r.role, is_self=r.user_id == p.id)}
                    for r in rows],
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
    # access tokens issued so far stop working NOW (the authenticator compares their iat with this instant)
    # clock_timestamp(), not now(): now() is the START of this transaction, which may predate a token a concurrent session issue committed
    conn.execute(text("UPDATE users_global SET tokens_valid_after = clock_timestamp() WHERE id = :u"), {"u": user_id})
    revoked = conn.execute(
        text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL RETURNING 1"), {"u": user_id}
    ).rowcount
    audit(conn, p, "member.mfa_reset", "user", str(user_id), {
        "had_mfa": bool(had and had.enabled), "revoked_sessions": revoked,
        "enrolment_now_required": _mfa_required(conn, settings, user_id)})
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="user", aggregate_id=user_id, event_type="member.mfa_reset",
                   payload={"by": str(p.id), "revoked_sessions": revoked})
    return {"status": "reset", "revoked_sessions": revoked}


ROLE_LABEL = {
    "isp_admin": "Administrador do provedor", "access_manager": "Gestor de Acesso", "engineer": "Engenheiro", "noc_n2": "NOC nível 2",
    "noc_n1": "NOC nível 1", "support": "Atendimento", "auditor": "Auditor", "platform_support": "Suporte da plataforma (delegado)",
    "edge_agent": "Agente Edge (conta de serviço)",
}


@router.get("/v1/roles")
def list_roles(p: Principal = Depends(require("roles:read"))) -> dict:
    """The system roles with what each one may do, straight from the permission catalog (ADR-0031), and which of them the caller may hand out."""
    mine = role_policy.ASSIGNABLE_BY.get(p.role, frozenset()) if p.can("members:manage") else frozenset()
    return {"roles": [
        {"role": r, "label": ROLE_LABEL.get(r, r), "assignable_by_me": r in mine,
         "permissions": [{"name": n, "risk": CATALOG[n].risk, "description": CATALOG[n].description} for n in CATALOG if n in ROLE_PERMISSIONS[r]]}
        for r in ROLE_PERMISSIONS]}


class RoleChangeIn(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=3, max_length=200)


# reason codes raised by app_change_member_role (the SQL function is the authority) -> HTTP status
ROLE_CHANGE_STATUS = {
    "member_not_found": 404, "cannot_change_own_role": 403, "role_cannot_grant": 403, "role_not_assignable": 403, "target_role_protected": 403,
    "role_unchanged": 409, "last_isp_admin": 409, "reason_required": 422,
}


@router.put("/v1/members/{user_id}/role")
def change_member_role(user_id: UUID, body: RoleChangeIn, p: Principal = Depends(require("members:manage"))) -> dict:
    """Changes a member's system role (ADR-0031). The whole change — validation of actor and transition, the write, ending the member's sessions, the
    audit record and the event — is ONE database function (`app_change_member_role`) that only the dedicated `fibercore_rbac` connection may execute:
    the application's normal database role cannot change a role at all, not even with forged session settings. The rules mirror role_policy (tested
    equal); this route only authenticates, validates the shape and maps the function's reason code."""
    if body.role not in ROLE_PERMISSIONS:
        raise HTTPException(422, "unknown role")
    engine = get_rbac_engine()
    if engine is None:
        raise HTTPException(503, "rbac_unavailable")   # fail closed: no dedicated connection configured, no role change
    try:
        with engine.begin() as c:
            res = c.execute(text("SELECT app_change_member_role(:a, :t, :u, :r, :why)"),
                            {"a": p.id, "t": p.tenant_id, "u": user_id, "r": body.role, "why": body.reason}).scalar_one()
    except DBAPIError as exc:
        state = str(getattr(exc.orig, "sqlstate", "") or "")
        code = str(getattr(getattr(exc.orig, "diag", None), "message_primary", "") or "")
        if state == "P0001" and code in ROLE_CHANGE_STATUS:
            raise HTTPException(ROLE_CHANGE_STATUS[code], code) from exc
        if state in ("40P01", "40001"):   # a deadlock/serialisation loser changed nothing: tell the caller to try again
            raise HTTPException(409, "conflict_retry") from exc
        raise
    return {"user_id": str(user_id), "role": body.role, "previous_role": res["previous_role"], "revoked_sessions": res["revoked_sessions"]}


@router.get("/v1/members/role-history")
def role_history(limit: int = Query(50, ge=1, le=200), p: Principal = Depends(require("audit:read")), conn: Connection = TENANT_CONN) -> dict:
    """Role changes of this workspace, newest first: who changed whose role, from what to what, why. Names come from current members only
    (a person who left shows no name); the reason is the free text the administrator typed and is shown as plain text."""
    rows = conn.execute(
        text(
            "SELECT a.id, a.created_at, a.actor_id, a.target_id, a.evidence_redacted AS ev, "
            "ua.display_name AS actor_name, ua.email AS actor_email, ut.display_name AS target_name, ut.email AS target_email "
            "FROM audit_log a "
            "LEFT JOIN tenant_memberships ma ON ma.tenant_id = a.tenant_id AND ma.user_id = a.actor_id "
            "LEFT JOIN users_global ua ON ua.id = ma.user_id "
            "LEFT JOIN tenant_memberships mt ON mt.tenant_id = a.tenant_id AND mt.user_id::text = a.target_id "
            "LEFT JOIN users_global ut ON ut.id = mt.user_id "
            "WHERE a.tenant_id = :t AND a.action = 'member.role_change' ORDER BY a.created_at DESC, a.id LIMIT :l"
        ),
        {"t": p.tenant_id, "l": limit + 1},
    ).all()
    return {"truncated": len(rows) > limit, "items": [
        {"id": str(r.id), "at": r.created_at.isoformat(), "from": r.ev.get("from"), "to": r.ev.get("to"), "reason": r.ev.get("reason"),
         "revoked_sessions": r.ev.get("revoked_sessions"),
         "actor": {"id": str(r.actor_id) if r.actor_id else None, "name": r.actor_name, "email": r.actor_email},
         "target": {"id": r.target_id, "name": r.target_name, "email": r.target_email}}
        for r in rows[:limit]]}
