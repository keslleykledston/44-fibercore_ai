"""Team management for administrators who are not engineers: see the people, invite, change a function, reset a password, remove, and read what happened.

Everything that changes who has access is a SECURITY DEFINER function executed only through the dedicated `fibercore_rbac` connection (migration 0027, same
discipline as the role change). A link (invite or password reset) is shown ONCE to whoever creates it; only its SHA-256 is stored; the invited person
chooses their own password, and nobody ever sees it."""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import _client_ip, _gate, _record, _throttled, audit
from app.core import role_policy, team_info
from app.core.db import get_engine, get_rbac_engine, scoped_connection
from app.core.security import ROLE_PERMISSIONS, hash_secret, verify_secret
from app.core.settings import Settings, get_settings

router = APIRouter()

INVITE_HOURS = 72
RESET_HOURS = 24
STATUS = {
    "role_cannot_grant": 403, "role_not_assignable": 403, "target_role_protected": 403, "cannot_remove_self": 403, "use_change_password": 403,
    "member_not_found": 404, "invite_not_found": 404,
    "already_member": 409, "invite_not_open": 409, "last_isp_admin": 409, "account_shared": 409, "account_exists": 409, "account_inactive": 409,
    "invite_used": 409, "invite_revoked": 409, "invite_expired": 410, "invite_invalid": 404, "reset_not_allowed": 409,
    "email_invalid": 422, "name_invalid": 422, "validity_invalid": 422, "reason_required": 422, "details_required": 422,
}


def _token() -> tuple[str, bytes]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).digest()


def _call(sql: str, args: dict) -> dict:
    engine = get_rbac_engine()
    if engine is None:
        raise HTTPException(503, "rbac_unavailable")   # fail closed: no dedicated connection, no change of who has access
    try:
        with engine.begin() as c:
            return c.execute(text(sql), args).scalar_one()
    except DBAPIError as exc:
        state = str(getattr(exc.orig, "sqlstate", "") or "")
        code = str(getattr(getattr(exc.orig, "diag", None), "message_primary", "") or "")
        if state == "P0001" and code in STATUS:
            raise HTTPException(STATUS[code], code) from exc
        if state == "23514" and "isp_admin" in code:   # the trigger of 0024
            raise HTTPException(409, "last_isp_admin") from exc
        if state in ("40P01", "40001"):
            raise HTTPException(409, "conflict_retry") from exc
        raise


# ---------------------------------------------------------------- the screen's data
@router.get("/v1/team")
def team(p: Principal = Depends(require("members:read")), conn: Connection = TENANT_CONN) -> dict:
    mine = role_policy.ASSIGNABLE_BY.get(p.role, frozenset()) if p.can("members:manage") else frozenset()
    members = conn.execute(
        text("SELECT m.user_id, u.email, u.display_name, m.role, COALESCE(mf.enabled, false) AS mfa_enabled "
             "FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id LEFT JOIN user_mfa mf ON mf.user_id = m.user_id "
             "WHERE m.tenant_id = :t AND u.is_active ORDER BY lower(u.display_name), u.email"), {"t": p.tenant_id}).all()
    invites = conn.execute(
        text("SELECT i.id, i.email, i.display_name, i.role, i.created_at, i.expires_at, u.display_name AS by_name, i.expires_at <= now() AS expired "
             "FROM member_invites i LEFT JOIN users_global u ON u.id = i.created_by "
             "WHERE i.tenant_id = :t AND i.purpose = 'invite' AND i.accepted_at IS NULL AND i.revoked_at IS NULL ORDER BY i.created_at DESC"),
        {"t": p.tenant_id}).all()
    can_manage = p.can("members:manage")
    rows = [{
        "user_id": str(m.user_id), "email": m.email, "name": m.display_name, "role": m.role, "role_label": team_info.LABEL.get(m.role, m.role),
        "role_summary": team_info.ROLE_INFO.get(m.role, {}).get("summary", ""), "mfa_enabled": m.mfa_enabled, "is_self": m.user_id == p.id,
        "can_change_role": can_manage and role_policy.can_change_any(p.role, m.role, is_self=m.user_id == p.id),
        "can_remove": can_manage and m.user_id != p.id and (p.role == "isp_admin" or m.role not in role_policy.PROTECTED_TARGETS),
        "can_reset_password": can_manage and m.user_id != p.id and (p.role == "isp_admin" or m.role not in role_policy.PROTECTED_TARGETS),
    } for m in members]
    return {
        "me": {"id": str(p.id), "role": p.role, "role_label": team_info.LABEL.get(p.role, p.role), "can_manage": can_manage,
               "assignable_roles": [r for r in team_info.HUMAN_ROLES if r in mine]},
        "summary": {"active": len(rows), "pending_invites": sum(1 for i in invites if not i.expired), "without_mfa": sum(1 for r in rows if not r["mfa_enabled"])},
        "members": rows,
        "invites": [{"id": str(i.id), "email": i.email, "name": i.display_name, "role": i.role, "role_label": team_info.LABEL.get(i.role, i.role),
                     "created_at": i.created_at.isoformat(), "expires_at": i.expires_at.isoformat(), "by": i.by_name, "expired": bool(i.expired)} for i in invites],
        "roles": [{"role": r, "label": i["label"], "summary": i["summary"], "can": i["can"], "cannot": i["cannot"], "assignable_by_me": r in mine}
                  for r, i in team_info.ROLE_INFO.items()],
        "capabilities": {"groups": [{"id": cid, "label": label} for cid, label, _ in team_info.CAPABILITIES], "matrix": team_info.matrix()},
    }


ACTIVITY = ("member.role_change", "member.invite", "member.invite_accepted", "member.invite_revoke", "member.remove", "member.password_reset_link",
            "member.password_reset_done", "member.mfa_reset", "account.password_change", "platform.delegation_grant", "platform.delegation_revoke",
            "bench.authorize", "bench.authorize_revoke")


@router.get("/v1/team/activity")
def activity(limit: int = Query(50, ge=1, le=200), p: Principal = Depends(require("audit:read")), conn: Connection = TENANT_CONN) -> dict:
    """What happened to access, newest first, as structured facts (the screen writes the sentences). E-mail addresses only for callers that read members."""
    rows = conn.execute(
        text("SELECT a.id, a.action, a.created_at, a.actor_id, a.target_id, a.target_type, a.evidence_redacted AS ev, ua.display_name AS actor_name, "
             "ut.display_name AS target_name, ut.email AS target_email "
             "FROM audit_log a LEFT JOIN users_global ua ON ua.id = a.actor_id "
             "LEFT JOIN users_global ut ON a.target_type = 'user' AND a.target_id ~ '^[0-9a-f-]{36}$' AND ut.id = CAST(a.target_id AS uuid) "
             "WHERE a.action = ANY(:acts) ORDER BY a.created_at DESC LIMIT :l"), {"acts": list(ACTIVITY), "l": limit + 1}).all()
    show = p.can("members:read")
    items = []
    for r in rows[:limit]:
        ev = r.ev or {}
        items.append({
            "id": str(r.id), "kind": r.action, "at": r.created_at.isoformat(), "actor": r.actor_name,
            "target": r.target_name or ev.get("name"), "email": (r.target_email or ev.get("email")) if show else None,
            "from": ev.get("from"), "to": ev.get("to") or ev.get("role"), "reason": ev.get("reason"), "hours": ev.get("hours"), "operation": ev.get("operation"),
            "from_label": team_info.LABEL.get(ev.get("from"), ev.get("from")) if ev.get("from") else None,
            "to_label": team_info.LABEL.get(ev.get("to") or ev.get("role"), ev.get("to") or ev.get("role")) if (ev.get("to") or ev.get("role")) else None,
        })
    return {"truncated": len(rows) > limit, "items": items}


# ---------------------------------------------------------------- invites
class InviteIn(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=32)


def _create_invite(p: Principal, email: str, name: str | None, role: str) -> dict:
    raw, digest = _token()
    res = _call("SELECT app_invite_create(:a, :t, :e, :n, :r, :h, :hours)",
                {"a": p.id, "t": p.tenant_id, "e": email, "n": name, "r": role, "h": digest, "hours": INVITE_HOURS})
    return {"id": res["id"], "email": res["email"], "role": res["role"], "role_label": team_info.LABEL.get(res["role"], res["role"]),
            "expires_at": res["expires_at"], "token": raw}


@router.post("/v1/team/invites", status_code=201)
def invite(body: InviteIn, p: Principal = Depends(require("members:manage"))) -> dict:
    """Creates an invite and returns its token ONCE: the screen builds the link from it. Nothing is sent by e-mail."""
    if body.role not in ROLE_PERMISSIONS:
        raise HTTPException(422, "unknown role")
    return _create_invite(p, str(body.email), body.name, body.role)


@router.post("/v1/team/invites/{invite_id}/renew", status_code=201)
def renew_invite(invite_id: UUID, p: Principal = Depends(require("members:manage")), conn: Connection = TENANT_CONN) -> dict:
    """A new link for a pending invite (the old one stops working). The data comes from the stored invite, never from the caller."""
    i = conn.execute(text("SELECT email, display_name, role FROM member_invites WHERE id = :i AND purpose = 'invite' AND accepted_at IS NULL AND revoked_at IS NULL"),
                     {"i": invite_id}).first()
    if i is None:
        raise HTTPException(404, "invite_not_found")
    return _create_invite(p, i.email, i.display_name, i.role)


@router.delete("/v1/team/invites/{invite_id}")
def cancel_invite(invite_id: UUID, p: Principal = Depends(require("members:manage"))) -> dict:
    _call("SELECT app_invite_revoke(:a, :t, :i)", {"a": p.id, "t": p.tenant_id, "i": invite_id})
    return {"status": "cancelled"}


# ---------------------------------------------------------------- people
@router.post("/v1/team/members/{user_id}/password-reset", status_code=201)
def password_reset_link(user_id: UUID, p: Principal = Depends(require("members:manage"))) -> dict:
    """A link (24 h, once) so the person chooses a new password. Refused when the account also belongs to another provider: no administrator of one
    provider may take a person over in somebody else's."""
    raw, digest = _token()
    res = _call("SELECT app_reset_create(:a, :t, :u, :h, :hours)", {"a": p.id, "t": p.tenant_id, "u": user_id, "h": digest, "hours": RESET_HOURS})
    return {"id": res["id"], "expires_at": res["expires_at"], "token": raw}


class RemoveIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


@router.post("/v1/team/members/{user_id}/remove")
def remove_member(user_id: UUID, body: RemoveIn, p: Principal = Depends(require("members:manage"))) -> dict:
    res = _call("SELECT app_member_remove(:a, :t, :u, :why)", {"a": p.id, "t": p.tenant_id, "u": user_id, "why": body.reason})
    return {"status": "removed", "previous_role": res["previous_role"]}


# ---------------------------------------------------------------- the link, opened by the invited person (no session)
def check_password(pw: str, email: str, name: str | None = None) -> str | None:
    """A reason code, or None. Length is what matters (NIST 800-63B); no composition rules, but not the obvious things."""
    if len(pw) < 12:
        return "password_short"
    if len(pw) > 256:
        return "password_long"
    low = pw.lower()
    local = email.split("@", 1)[0].lower()
    if len(set(pw)) < 5 or low in {"123456789012", "password1234", "senha1234567", "qwertyuiop12"} or (len(local) >= 4 and local in low):
        return "password_weak"
    if name and len(name.strip()) >= 4 and name.strip().lower() in low:
        return "password_weak"
    return None


def _digest(token: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", token):
        raise HTTPException(404, "invite_invalid")
    return hashlib.sha256(token.encode()).digest()


@router.get("/v1/invites/{token}")
def invite_preview(token: str, request: Request, settings: Settings = Depends(get_settings)) -> dict:
    """What the page shows before anything is typed. Throttled by source; says nothing about accounts unless the link is valid (the holder is the invitee)."""
    digest = _digest(token)
    ip = _client_ip(request, settings)
    with scoped_connection(get_engine()) as conn:
        if _gate(conn, f"invite-view:{ip}", ip):
            raise _throttled()
        _record(conn, f"invite-view:{ip}", ip, True)
    res = _call("SELECT app_invite_lookup(:h)", {"h": digest})
    if res["state"] != "valid":
        return {"state": res["state"]}
    return {"state": "valid", "purpose": res["purpose"], "tenant_name": res["tenant_name"], "email": res["email"], "name": res.get("display_name"),
            "role_label": team_info.LABEL.get(res.get("role"), res.get("role")) if res.get("role") else None, "inviter": res.get("inviter"),
            "expires_at": res["expires_at"], "account_exists": bool(res["account_exists"]) and res["purpose"] == "invite"}


class AcceptIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@router.post("/v1/invites/{token}/accept")
def invite_accept(token: str, body: AcceptIn, request: Request, settings: Settings = Depends(get_settings)) -> dict:
    """New person: chooses a name and a password. Existing account: proves it with the CURRENT password (nobody joins a workspace by somebody else's
    invitation alone). Password reset: chooses a new password. Failures are throttled per link and per source."""
    digest = _digest(token)
    ip = _client_ip(request, settings)
    key = f"invite:{digest.hex()[:16]}"
    info = _call("SELECT app_invite_lookup(:h)", {"h": digest})
    if info["state"] != "valid":
        raise HTTPException({"used": 409, "revoked": 409, "expired": 410}.get(info["state"], 404), f"invite_{info['state']}" if info["state"] != "invalid" else "invite_invalid")
    existing = bool(info["account_exists"]) and info["purpose"] == "invite"
    locked, ok = False, True
    with scoped_connection(get_engine()) as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})
        if _gate(conn, key, ip):
            locked = True
        else:
            ok = (not existing) or (bool(info["account_active"]) and verify_secret(info.get("password_hash"), body.password))
            _record(conn, key, ip, ok)
    if locked:         # raised AFTER the transaction: the failed attempt must be recorded (a raise inside would roll it back)
        raise _throttled()
    if not ok:
        raise HTTPException(401, "invalid credentials")
    new_hash = None
    if not existing:
        reason = check_password(body.password, info["email"], body.name or info.get("display_name"))
        if reason:
            raise HTTPException(422, reason)
        new_hash = hash_secret(body.password)
    name = body.name or info.get("display_name")
    if not existing and info["purpose"] == "invite" and not name:
        raise HTTPException(422, "details_required")
    res = _call("SELECT app_invite_accept(:h, :n, :p, :v)", {"h": digest, "n": name, "p": new_hash, "v": existing})
    return {"status": "accepted", "purpose": res["purpose"]}
