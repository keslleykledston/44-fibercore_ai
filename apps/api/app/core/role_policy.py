"""Who may give which role to whom (ADR-0031, delivery 2). PURE: roles in, a reason code out; the API applies it under a per-workspace lock.

Only system roles exist for now. `edge_agent` is for service accounts (never a human membership) and `platform_support` is not assignable until the
delegation delivery (8 h, with a reason) exists; both are refused for everyone."""
from __future__ import annotations

NEVER_ASSIGNABLE = frozenset({"edge_agent", "platform_support"})
# roles each granter role may hand out; a role that is not a key here cannot grant anything
ASSIGNABLE_BY: dict[str, frozenset[str]] = {
    "isp_admin": frozenset({"isp_admin", "access_manager", "engineer", "noc_n2", "noc_n1", "support", "auditor"}),
    "access_manager": frozenset({"engineer", "noc_n2", "noc_n1", "support", "auditor"}),
}
# roles whose holders only an isp_admin may change (an access_manager can neither promote to nor demote from them)
PROTECTED_TARGETS = frozenset({"isp_admin", "access_manager", "platform_support", "edge_agent"})

for _granter, _roles in ASSIGNABLE_BY.items():  # a configuration slip must stop the app, not hand out a forbidden role
    if not NEVER_ASSIGNABLE.isdisjoint(_roles) or _granter in NEVER_ASSIGNABLE:
        raise RuntimeError(f"role_policy: {_granter!r} may hand out a never-assignable role")


def check_change(actor_role: str, target_current: str, new_role: str, *, is_self: bool) -> str | None:
    """None = allowed; otherwise a stable reason code."""
    if is_self:
        return "cannot_change_own_role"
    allowed = ASSIGNABLE_BY.get(actor_role)
    if allowed is None:
        return "role_cannot_grant"
    if new_role in NEVER_ASSIGNABLE or new_role not in allowed:
        return "role_not_assignable"
    if target_current in PROTECTED_TARGETS and actor_role != "isp_admin":
        return "target_role_protected"
    if new_role == target_current:
        return "role_unchanged"
    return None


def can_change_any(actor_role: str, target_current: str, *, is_self: bool) -> bool:
    """For the UI: is there at least one role this actor could give this member?"""
    return any(check_change(actor_role, target_current, r, is_self=is_self) is None for r in (ASSIGNABLE_BY.get(actor_role) or ()))
