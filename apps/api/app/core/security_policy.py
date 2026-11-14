"""Política de segurança por organização (ADR-0049 D1): MFA obrigatório por papel, que só APERTA o piso do ambiente.

O piso (`required_mfa_roles(settings)`: `MFA_REQUIRED_ROLES` + `ALWAYS_MFA_ROLES`) nunca é afrouxado: a regra efetiva de uma organização é piso ∪ papéis dela. Linha ausente, vazia ou ilegível
= só o piso (uma leitura que FALHA propaga o erro: a requisição falha fechada, não cai para "sem política").
"""
from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import Connection, text

from app.core.settings import Settings, required_mfa_roles

HUMAN_ROLES = ("isp_admin", "access_manager", "engineer", "noc_n2", "noc_n1", "support", "auditor")   # same list as the CHECK of migration 0057


def org_roles(conn: Connection, tenant_id: UUID) -> frozenset[str]:
    row = conn.execute(text("SELECT mfa_required_roles FROM tenant_security_policy WHERE tenant_id = :t"), {"t": tenant_id}).scalar()
    return frozenset(row or ())


def effective_roles(conn: Connection, settings: Settings, tenant_id: UUID) -> frozenset[str]:
    return required_mfa_roles(settings) | org_roles(conn, tenant_id)


def mfa_required(conn: Connection, settings: Settings, memberships: Mapping[UUID, str]) -> bool:
    """Does ANY of the account's organizations require a second factor of the role the account holds there? `memberships` is tenant_id -> role. Needs a connection scoped to the user."""
    floor = required_mfa_roles(settings)
    if not memberships:
        return False
    if any(role in floor for role in memberships.values()):
        return True
    rows = conn.execute(text("SELECT tenant_id, mfa_required_roles FROM tenant_security_policy WHERE tenant_id = ANY(:ts)"), {"ts": list(memberships)}).all()
    return any(memberships[r.tenant_id] in (r.mfa_required_roles or ()) for r in rows)
