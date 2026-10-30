from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import Connection, text

from app.core.db import get_engine, scoped_connection
from app.core.memberships import active_roles
from app.core.permissions import CATALOG, require_known
from app.core.security import ROLE_PERMISSIONS, decode_token
from app.core.settings import Settings, get_settings, required_mfa_roles


@dataclass(frozen=True)
class Principal:
    id: UUID
    kind: str
    tenant_id: UUID
    role: str
    edge_id: UUID | None = None
    mfa_at: float | None = None  # epoch s of the last second factor proved in this session (users only); see mfa_is_recent

    def can(self, perm: str) -> bool:
        return perm in ROLE_PERMISSIONS.get(self.role, frozenset())


def _unauth() -> HTTPException:
    return HTTPException(401, "invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"})


def assert_user_token_current(conn, claims) -> None:
    """The ONE place that decides whether a user access token still counts: the account must be active AND the token must not predate
    users_global.tokens_valid_after (set when the account is signed out everywhere, e.g. an administrator MFA reset)."""
    u = conn.execute(
        text("SELECT is_active, extract(epoch FROM tokens_valid_after) AS valid_after FROM users_global WHERE id = :u"), {"u": claims.sub},
    ).first()
    if not u or not u.is_active:
        raise _unauth()
    if u.valid_after is not None and claims.iat < float(u.valid_after):
        raise _unauth()


def authenticated_user_id(authorization: str | None, settings: Settings) -> UUID:
    """For routes that need a USER session but no tenant (workspaces, MFA self-service): same checks as get_principal, no membership."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauth()
    try:
        claims = decode_token(settings, authorization[7:].strip())
    except (jwt.PyJWTError, ValueError) as exc:
        raise _unauth() from exc
    if claims.kind != "user":
        raise HTTPException(403, "users only")
    with scoped_connection(get_engine(), user_id=claims.sub) as conn:
        assert_user_token_current(conn, claims)
    return claims.sub


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
        assert_user_token_current(conn, claims)
        memberships = active_roles(conn, claims.sub)  # memberships + live platform delegations, resolved on EVERY request
        required = required_mfa_roles(settings)
        if required and required & set(memberships.values()):
            has_mfa = conn.execute(text("SELECT enabled FROM user_mfa WHERE user_id = :u"), {"u": claims.sub}).scalar()
            if not has_mfa:  # policy: finish MFA enrolment first (the /v1/auth/* routes stay open so the user can)
                raise HTTPException(403, "mfa_enrolment_required")
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
    return Principal(claims.sub, "user", tid, memberships[tid], mfa_at=claims.mfa_at)


def mfa_is_recent(p: Principal, settings: Settings) -> bool:
    """A second factor proved in the last MFA_RECENT_SECONDS (a timestamp in the future counts as not recent)."""
    if p.mfa_at is None:
        return False
    age = time.time() - p.mfa_at
    return 0 <= age <= settings.mfa_recent_seconds


def require(perm: str):
    require_known(perm)  # a permission outside the catalog is a programming error: the app does not even import
    needs_recent = CATALOG[perm].mfa_recent

    def dep(p: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> Principal:
        if not p.can(perm):
            raise HTTPException(403, "forbidden")
        if needs_recent and settings.mfa_recent_enforce and p.kind == "user" and not mfa_is_recent(p, settings):
            raise HTTPException(403, "mfa_recent_required")  # the client answers with POST /v1/auth/mfa/step-up and repeats the call
        return p

    dep.rbac_permission = perm  # type: ignore[attr-defined]  # read by the route inventory test and the generated matrix
    return dep


def tenant_conn(p: Principal = Depends(get_principal)) -> Iterator[Connection]:
    """Always use TENANT_CONN (Depends(tenant_conn, scope="function")): the transaction must COMMIT before the response is sent. With the
    default request scope the commit runs after the client already has its 2xx, so a follow-up call (read-your-writes) can race it."""
    with scoped_connection(get_engine(), user_id=p.id, tenant_id=p.tenant_id) as conn:
        yield conn


TENANT_CONN = Depends(tenant_conn, scope="function")
