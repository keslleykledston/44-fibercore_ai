from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import Connection, text

from app.core.db import get_engine, scoped_connection
from app.core import api_tokens
from app.core import scope as scope_mod
from app.core import security_policy
from app.core.memberships import PLATFORM_ROLE as PLATFORM_ROLE_NAME
from app.core.memberships import active_roles
from app.core.permissions import CATALOG, require_known
from app.core.ratelimit import TokenBucketLimiter
from app.core.security import ROLE_PERMISSIONS, decode_token
from app.core.settings import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Principal:
    id: UUID
    kind: str
    tenant_id: UUID
    role: str
    edge_id: UUID | None = None
    mfa_at: float | None = None  # epoch s of the last second factor proved in this session (users only); see mfa_is_recent
    scope: frozenset[UUID] | None = None  # ADR-0049 D2: None = the whole provider; otherwise the OLT ids this person may see (resolved from the database on EVERY request)
    grants: frozenset[str] | None = None  # ADR-0051: an API token holds EXACTLY the permissions it was given (never a role's)

    def can(self, perm: str) -> bool:
        if self.kind == "api_token":
            return perm in (self.grants or frozenset())
        if self.scope is not None and perm not in scope_mod.SCOPED_ALLOWED_PERMISSIONS:
            return False   # a scoped principal holds the role's permissions INTERSECTED with the closed read-only list
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


def _assert_org_active(conn, tenant_id: UUID) -> None:
    """ADR-0047 D1: a suspended organization answers nothing (users AND the Edge's service account), checked on EVERY request, so a reactivation applies at once and no token is revoked.
    A missing row counts as not active (fail closed). Login stays open (the account is not suspended, the organization is)."""
    status = conn.execute(text("SELECT status FROM tenants WHERE id = :t"), {"t": tenant_id}).scalar()
    if status != "active":
        raise HTTPException(403, "organization_suspended")


_TOKEN_LIMITERS: dict[tuple[int, int], TokenBucketLimiter] = {}


def _api_token_principal(bearer: str, settings: Settings) -> Principal:
    """ADR-0051: an `fcat_` bearer. Any malformed, unknown, revoked or expired token is the SAME 401 (nothing says which). The organization must be active (checked now, like every request)
    and the token is rate limited on its own bucket (429 + Retry-After)."""
    if not api_tokens.TOKEN_RE.match(bearer):
        raise _unauth()
    with scoped_connection(get_engine()) as conn:
        row = conn.execute(text("SELECT tenant_id, id, permissions FROM app_api_token_lookup(:h)"), {"h": api_tokens.digest(bearer)}).first()
    if row is None:
        raise _unauth()
    with scoped_connection(get_engine(), user_id=row.id, tenant_id=row.tenant_id) as conn:
        _assert_org_active(conn, row.tenant_id)
    key = (api_tokens.DEFAULT_BURST, api_tokens.DEFAULT_PER_MINUTE)
    lim = _TOKEN_LIMITERS.get(key) or _TOKEN_LIMITERS.setdefault(key, TokenBucketLimiter(burst=key[0], per_minute=key[1]))
    wait = lim.take(f"tok:{row.id}")
    if wait > 0:
        raise HTTPException(429, "token_rate_limited", headers={"Retry-After": str(lim.retry_after(wait))})
    return Principal(row.id, "api_token", row.tenant_id, "api_token", grants=frozenset(row.permissions))


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
    bearer = authorization[7:].strip()
    if api_tokens.looks_like_token(bearer):
        return _api_token_principal(bearer, settings)
    try:
        claims = decode_token(settings, bearer)
    except (jwt.PyJWTError, ValueError) as exc:
        raise _unauth() from exc

    engine = get_engine()
    if claims.kind == "service":
        with scoped_connection(engine, user_id=claims.sub, tenant_id=claims.tenant_id) as conn:
            row = conn.execute(
                text("SELECT role, is_active, edge_id FROM service_accounts WHERE id = :i AND tenant_id = :t"),
                {"i": claims.sub, "t": claims.tenant_id},
            ).first()
            if row and row.is_active:
                _assert_org_active(conn, claims.tenant_id)
        if not row or not row.is_active:
            raise _unauth()
        return Principal(claims.sub, "service", claims.tenant_id, row.role, row.edge_id)

    with scoped_connection(engine, user_id=claims.sub) as conn:
        assert_user_token_current(conn, claims)
        memberships = active_roles(conn, claims.sub)  # memberships + live platform delegations, resolved on EVERY request
        if security_policy.mfa_required(conn, settings, memberships):   # the environment's floor plus what each organization added (ADR-0049 D1)
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
    with scoped_connection(engine, user_id=claims.sub, tenant_id=tid) as conn:   # only after the membership was validated above (scoped_connection's own rule)
        _assert_org_active(conn, tid)
        # a platform delegate is never scoped (its role is not a membership); a member with a `member_scopes` row is, whatever the role they hold now
        scope = scope_mod.resolve(conn, tid, claims.sub) if memberships[tid] != PLATFORM_ROLE_NAME else None
    return Principal(claims.sub, "user", tid, memberships[tid], mfa_at=claims.mfa_at, scope=scope)


def mfa_is_recent(p: Principal, settings: Settings) -> bool:
    """A second factor proved in the last MFA_RECENT_SECONDS (a timestamp in the future counts as not recent)."""
    if p.mfa_at is None:
        return False
    age = time.time() - p.mfa_at
    return 0 <= age <= settings.mfa_recent_seconds


def ensure_permission(p: Principal, settings: Settings, perm: str) -> None:
    """The check `require` makes, for a handler that learns WHICH permission it needs only from the body (ADR-0046: the `kind` of a delivery): the role, then the recent second factor."""
    require_known(perm)
    if not p.can(perm):
        raise HTTPException(403, "forbidden")
    if CATALOG[perm].mfa_recent and settings.mfa_recent_enforce and p.kind == "user" and not mfa_is_recent(p, settings):
        raise HTTPException(403, "mfa_recent_required")  # the client answers with POST /v1/auth/mfa/step-up and repeats the call


def require(perm: str):
    require_known(perm)  # a permission outside the catalog is a programming error: the app does not even import

    def dep(p: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> Principal:
        ensure_permission(p, settings, perm)
        return p

    dep.rbac_permission = perm  # type: ignore[attr-defined]  # read by the route inventory test and the generated matrix
    return dep


def require_any(*perms: str):
    """At least ONE of the permissions (the handler then checks the one its input needs with `ensure_permission`). Listed for the inventory and the matrix as every permission it accepts."""
    for perm in perms:
        require_known(perm)

    def dep(p: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> Principal:
        held = [perm for perm in perms if p.can(perm)]
        if not held:
            raise HTTPException(403, "forbidden")
        ensure_permission(p, settings, held[0])   # the first held decides the recent-factor rule; the handler repeats it for the permission it really needs
        return p

    dep.rbac_permissions = tuple(perms)  # type: ignore[attr-defined]
    return dep


PLATFORM_MFA_MAX_SECONDS = 600   # the database function checks the same 10 minutes (ADR-0031); a longer MFA_RECENT_SECONDS never loosens a platform route


@dataclass(frozen=True)
class PlatformOperator:
    id: UUID
    mfa_at: float | None


def require_platform_operator(perm: str):
    """Guard of the platform routes (no tenant in the token, ADR-0046 D1). `perm` is a catalog permission that NO organization role holds: it is decided by the account
    flag `users_global.is_platform_operator` (set only by the owner's CLI), never by a role. Order: a valid user session (401), an ACTIVE operator account (403 `forbidden`, the same
    answer for every other account, so nothing is revealed), then a second factor proved in the last 10 minutes (403 `mfa_recent_required`, said only to an operator). This
    check always applies, whatever MFA_RECENT_ENFORCE says."""
    require_known(perm)

    def dep(authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> PlatformOperator:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise _unauth()
        try:
            claims = decode_token(settings, authorization[7:].strip())
        except (jwt.PyJWTError, ValueError) as exc:
            raise _unauth() from exc
        if claims.kind != "user":
            raise HTTPException(403, "forbidden")
        with scoped_connection(get_engine(), user_id=claims.sub) as conn:
            assert_user_token_current(conn, claims)   # active account, not revoked
            is_operator = conn.execute(text("SELECT is_platform_operator FROM users_global WHERE id = :u"), {"u": claims.sub}).scalar()
        if not is_operator:
            raise HTTPException(403, "forbidden")
        window = min(settings.mfa_recent_seconds, PLATFORM_MFA_MAX_SECONDS)
        if claims.mfa_at is None or not 0 <= time.time() - claims.mfa_at <= window:
            raise HTTPException(403, "mfa_recent_required")
        return PlatformOperator(claims.sub, claims.mfa_at)

    dep.rbac_permission = perm  # type: ignore[attr-defined]  # the route inventory lists it; `test_rbac_inventory` pins that no role holds it
    return dep


def tenant_conn(p: Principal = Depends(get_principal)) -> Iterator[Connection]:
    """Always use TENANT_CONN (Depends(tenant_conn, scope="function")): the transaction must COMMIT before the response is sent. With the
    default request scope the commit runs after the client already has its 2xx, so a follow-up call (read-your-writes) can race it."""
    with scoped_connection(get_engine(), user_id=p.id, tenant_id=p.tenant_id, scope=scope_mod.to_setting(p.scope)) as conn:
        yield conn


TENANT_CONN = Depends(tenant_conn, scope="function")

_INGEST_LIMITERS: dict[tuple[int, int], TokenBucketLimiter] = {}


_ORG_BUDGETS: dict[UUID, tuple[float, tuple[int, int]]] = {}   # tenant -> (read at, (burst, per_minute))
ORG_BUDGET_TTL = 30.0   # seconds: an operator's change reaches the intake routes within this; one tiny query per organization per TTL


def _org_budget(p: Principal, settings: Settings) -> tuple[int, int]:
    """The organization's intake budget: its override in `tenant_limits` over the code default. A read failure falls back to the default (never blocks the intake)."""
    now = time.monotonic()
    hit = _ORG_BUDGETS.get(p.tenant_id)
    if hit is not None and now - hit[0] < ORG_BUDGET_TTL:
        return hit[1]
    budget = (settings.org_ingest_burst, settings.org_ingest_per_minute)
    try:
        from app.core import limits
        with scoped_connection(get_engine(), user_id=p.id, tenant_id=p.tenant_id) as conn:
            eff = limits.effective(conn, p.tenant_id, settings)
        budget = (eff["ingest_burst"], eff["ingest_per_minute"])
    except Exception:   # noqa: BLE001 - fail open to the default, but say so
        log.warning("organization intake budget unreadable (tenant %s): default used", p.tenant_id)
    if len(_ORG_BUDGETS) >= 10_000:
        _ORG_BUDGETS.clear()
    _ORG_BUDGETS[p.tenant_id] = (now, budget)
    return budget


EDGE_BACKOFF_HEADER = "X-Edge-Backoff"   # value "retry-after": this agent treats 429 as "wait for Retry-After; the item is not failed"


def edge_ingest_limit(request: Request, p: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> None:
    """Per-agent budget for the Edge intake routes: 429 `edge_rate_limited` + Retry-After (the Edge treats 429 as "keep it and send again", so no data is lost). Declare it AFTER
    `require(...)` in the route so an unauthenticated or unauthorised caller never spends (or learns about) an agent's budget."""
    if settings.edge_ingest_limit == "off":
        return
    if settings.edge_ingest_limit == "capable" and request.headers.get(EDGE_BACKOFF_HEADER, "").lower() != "retry-after":
        return   # an Edge that does not say it understands 429 would count it as a failed attempt: never limit it (version skew)
    key = (settings.edge_ingest_burst, settings.edge_ingest_per_minute)
    lim = _INGEST_LIMITERS.get(key)
    if lim is None:
        lim = _INGEST_LIMITERS.setdefault(key, TokenBucketLimiter(burst=key[0], per_minute=key[1]))
    wait = lim.take(f"{p.tenant_id}:{p.edge_id or p.id}")
    if wait > 0:
        log.warning("edge intake rate-limited (tenant %s, agent %s)", p.tenant_id, p.edge_id or p.id)
        raise HTTPException(429, "edge_rate_limited", headers={"Retry-After": str(lim.retry_after(wait))})
    # ADR-0047 D3: one more bucket per ORGANIZATION (all its agents together), so a provider with many agents cannot starve the others. Same answer to the Edge (429, keep and resend).
    org_key = _org_budget(p, settings)
    org_lim = _INGEST_LIMITERS.get(org_key)
    if org_lim is None:
        org_lim = _INGEST_LIMITERS.setdefault(org_key, TokenBucketLimiter(burst=org_key[0], per_minute=org_key[1]))
    wait = org_lim.take(f"org:{p.tenant_id}")
    if wait > 0:
        log.warning("organization intake rate-limited (tenant %s)", p.tenant_id)
        raise HTTPException(429, "organization_rate_limited", headers={"Retry-After": str(org_lim.retry_after(wait))})

