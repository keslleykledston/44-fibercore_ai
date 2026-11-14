"""Security policy of the organization (ADR-0049 D1): which roles must have a second factor, ON TOP of the environment's floor.

It can only tighten: the effective rule is the floor ∪ the organization's roles (`app/core/security_policy.py`), so emptying the list never goes below the floor. Changing it is a
`tenant:security_policy` act (R3, only `isp_admin`). Two safeguards against locking people out: the platform must be able to enrol an authenticator (`MFA_ENCRYPTION_KEY`), and the
administrator who tightens must already have a second factor if the change reaches their own role. Members affected who have none yet are sent to enrol on their next request (the
`/v1/auth/*` routes stay open for that, the same path the environment's own policy uses).
"""
from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import security_policy
from app.core.settings import Settings, get_settings, required_mfa_roles
from app.events import outbox

router = APIRouter()


class PolicyIn(BaseModel):
    mfa_required_roles: list[str] = Field(max_length=len(security_policy.HUMAN_ROLES))


def _view(conn: Connection, p: Principal, settings: Settings) -> dict:
    floor = required_mfa_roles(settings)
    mine = security_policy.org_roles(conn, p.tenant_id)
    effective = floor | mine
    without = conn.execute(
        text("SELECT m.role, count(*) AS n FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id LEFT JOIN user_mfa f ON f.user_id = m.user_id "
             "WHERE m.tenant_id = :t AND u.is_active AND NOT COALESCE(f.enabled, false) AND m.role = ANY(:r) GROUP BY m.role"),
        {"t": p.tenant_id, "r": sorted(effective)}).all()
    return {"floor": sorted(floor), "organization": sorted(mine), "effective": sorted(effective), "selectable": list(security_policy.HUMAN_ROLES),
            "members_without_mfa": {r.role: r.n for r in without}, "mfa_available": bool(settings.mfa_encryption_key), "can_edit": p.can("tenant:security_policy")}


@router.get("/v1/security-policy")
def read_policy(p: Principal = Depends(require("tenant:read")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)) -> dict:
    return _view(conn, p, settings)


@router.put("/v1/security-policy")
def set_policy(body: PolicyIn, p: Principal = Depends(require("tenant:security_policy")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)) -> dict:
    roles = sorted(set(body.mfa_required_roles))
    if any(r not in security_policy.HUMAN_ROLES for r in roles):
        raise HTTPException(422, "role_invalid")
    if roles and not settings.mfa_encryption_key:
        raise HTTPException(409, "mfa_unavailable")   # no authenticator can be enrolled here: requiring one would lock people out
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"security-policy:{p.tenant_id}"})
    before = sorted(security_policy.org_roles(conn, p.tenant_id))
    new_effective = required_mfa_roles(settings) | set(roles)
    if p.role in new_effective and not conn.execute(text("SELECT enabled FROM user_mfa WHERE user_id = :u"), {"u": p.id}).scalar():
        raise HTTPException(409, "enable_your_mfa_first")   # whoever tightens must not lock themselves out
    if roles == before:
        return {**_view(conn, p, settings), "changed": False}
    conn.execute(
        text("INSERT INTO tenant_security_policy (tenant_id, mfa_required_roles, updated_by) VALUES (:t, :r, :u) "
             "ON CONFLICT (tenant_id) DO UPDATE SET mfa_required_roles = EXCLUDED.mfa_required_roles, updated_by = EXCLUDED.updated_by, updated_at = now()"),
        {"t": p.tenant_id, "r": roles, "u": p.id})
    view = _view(conn, p, settings)
    audit(conn, p, "tenant.security_policy.changed", "tenant", str(p.tenant_id), {"from": before, "to": roles, "members_without_mfa": sum(view["members_without_mfa"].values())})
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="tenant", aggregate_id=p.tenant_id, event_type="tenant.security_policy.changed", payload={"by": str(p.id)})
    return {**view, "changed": True}


__all__ = ["router"]
