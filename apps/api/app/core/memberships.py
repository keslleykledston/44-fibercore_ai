"""The workspaces a user can act in and the role they hold there (ADR-0031).

A role comes from `tenant_memberships`, except `platform_support`, which exists ONLY as a delegation: an unrevoked row of
`membership_delegations` that has not expired (judged by the database clock at this statement), granted to an account that is still marked as a
platform operator and still active. Every request resolves it again, so a revocation or an expiry ends the access at once, whatever the token says.
A real membership of the workspace always wins over a delegation.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, text

PLATFORM_ROLE = "platform_support"


def active_roles(conn: Connection, user_id: UUID) -> dict[UUID, str]:
    """tenant_id -> role for the memberships and the live delegations of this account. Needs a connection scoped to the user (app.user_id)."""
    roles = {r.tenant_id: r.role for r in conn.execute(text("SELECT tenant_id, role FROM tenant_memberships WHERE user_id = :u"), {"u": user_id})}
    for r in conn.execute(
        text("SELECT DISTINCT d.tenant_id FROM membership_delegations d JOIN users_global u ON u.id = d.user_id "
             "WHERE d.user_id = :u AND d.revoked_at IS NULL AND clock_timestamp() < d.expires_at AND u.is_active AND u.is_platform_operator"),
        {"u": user_id},
    ):
        roles.setdefault(r.tenant_id, PLATFORM_ROLE)
    return roles
