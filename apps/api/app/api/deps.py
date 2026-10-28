from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import Connection, text

from app.core.db import get_engine, scoped_connection
from app.core.security import ROLE_PERMISSIONS, decode_token
from app.core.settings import Settings, get_settings


@dataclass(frozen=True)
class Principal:
    id: UUID
    kind: str
    tenant_id: UUID
    role: str
    edge_id: UUID | None = None

    def can(self, perm: str) -> bool:
        return perm in ROLE_PERMISSIONS.get(self.role, frozenset())


def _unauth() -> HTTPException:
    return HTTPException(401, "invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"})


def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_workspace_id: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Authenticate, then derive tenant+role from DB membership. The header only *selects* among
    memberships the user really has; anything else is a 404 that does not reveal existence."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauth()
    try:
        claims = decode_token(settings, authorization[7:].strip())
    except (jwt.PyJWTError, ValueError) as exc:
        raise _unauth() from exc

    engine = get_engine()
    if claims.kind == "service":
        with scoped_connection(engine, user_id=claims.sub, tenant_id=claims.tenant_id) as conn:
            row = conn.execute(
                text("SELECT role, is_active, edge_id FROM service_accounts WHERE id = :i AND tenant_id = :t"),
                {"i": claims.sub, "t": claims.tenant_id},
            ).first()
        if not row or not row.is_active:
            raise _unauth()
        return Principal(claims.sub, "service", claims.tenant_id, row.role, row.edge_id)

    with scoped_connection(engine, user_id=claims.sub) as conn:
        active = conn.execute(
            text("SELECT is_active FROM users_global WHERE id = :u"), {"u": claims.sub}
        ).scalar()
        if not active:
            raise _unauth()
        memberships = {
            r.tenant_id: r.role
            for r in conn.execute(text("SELECT tenant_id, role FROM tenant_memberships WHERE user_id = :u"), {"u": claims.sub})
        }
    if x_workspace_id:
        try:
            tid = UUID(x_workspace_id)
        except ValueError as exc:
            raise HTTPException(404, "tenant not found") from exc
    elif len(memberships) == 1:
        tid = next(iter(memberships))
    else:
        raise HTTPException(400, "X-Workspace-ID required")
    if tid not in memberships:
        raise HTTPException(404, "tenant not found")
    return Principal(claims.sub, "user", tid, memberships[tid])


def require(perm: str):
    def dep(p: Principal = Depends(get_principal)) -> Principal:
        if not p.can(perm):
            raise HTTPException(403, "forbidden")
        return p

    return dep


def tenant_conn(p: Principal = Depends(get_principal)) -> Iterator[Connection]:
    with scoped_connection(get_engine(), user_id=p.id, tenant_id=p.tenant_id) as conn:
        yield conn
