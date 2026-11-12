"""Organizations (providers) created and listed by the PLATFORM OPERATOR, from the screen (ADR-0046 D1).

No tenant in the token (same family as `/v1/auth/workspaces`): the guard is `require_platform_operator`, i.e. the account flag `is_platform_operator` (set only by the owner's CLI),
an active account and a second factor proved in the last 10 minutes. No organization role holds `platform:organizations`.

The creation is ONE database function (migration 0053, `platform_create_organization`): owner = the schema owner, fixed search_path, EXECUTE only for the application role, and it
re-checks the actor itself (it does not trust a session variable). The application role has no INSERT on `tenants`. This route calls it and, in the SAME transaction, writes
`platform.organization.requested` (same `request_id` as the function's `platform.organization.created`) into the new organization's audit trail: the pair is what the metric
`fibercore_organizations_without_api_trail` looks for, so a creation made OUTSIDE this route (direct SQL) shows up as a `created` with no `requested`.

Declared limit (ADR-0046 D1, R-3): the database cannot prove the operator started the call; whoever controls the API or the application role can pick `p_actor`. Not fixed here.
The operator does NOT become a member of the organization created; the first administrator is an invite (one link, shown once, 72 h) to the e-mail given."""
from __future__ import annotations

import json
import time
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.deps import PLATFORM_MFA_MAX_SECONDS, PlatformOperator, assert_user_token_current, require_platform_operator
from app.core.db import get_engine, scoped_connection
from app.core.security import decode_token
from app.core.settings import Settings, get_settings

router = APIRouter()
PERM = "platform:organizations"

# what the database function raises (message_primary) -> HTTP. Nothing else is ever echoed.
STATUS = {
    "platform_forbidden": (403, "forbidden"), "mfa_recent_required": (403, "mfa_recent_required"),
    "organization_name_taken": (409, "organization_name_taken"), "organization_rate_limited": (429, "organization_rate_limited"),
    "organization_name_invalid": (422, "organization_name_invalid"), "organization_email_invalid": (422, "organization_email_invalid"),
    "organization_admin_name_invalid": (422, "organization_admin_name_invalid"),
}


def _map(exc: DBAPIError) -> HTTPException | None:
    state = str(getattr(exc.orig, "sqlstate", "") or "")
    code = str(getattr(getattr(exc.orig, "diag", None), "message_primary", "") or "")
    if state == "P0001" and code in STATUS:
        status, detail = STATUS[code]
        return HTTPException(status, detail, headers={"Retry-After": "3600"} if status == 429 else None)
    return None


@router.get("/v1/platform/status")
def platform_status(response: Response, authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> dict:
    """The caller's OWN account, and nothing else: is it a platform operator, and did its session prove the second factor in the last 10 minutes? The screen uses it to show or hide the
    menu item and to ask for the second factor BEFORE the form. It decides nothing: the routes above check again, every time, and answer 403 to everybody else."""
    response.headers["Cache-Control"] = "no-store"
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(settings, authorization[7:].strip())
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(401, "invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"}) from exc
    if claims.kind != "user":
        return {"operator": False, "mfa_recent": False}
    with scoped_connection(get_engine(), user_id=claims.sub) as conn:
        assert_user_token_current(conn, claims)
        operator = bool(conn.execute(text("SELECT is_platform_operator FROM users_global WHERE id = :u"), {"u": claims.sub}).scalar())
    window = min(settings.mfa_recent_seconds, PLATFORM_MFA_MAX_SECONDS)
    recent = operator and claims.mfa_at is not None and 0 <= time.time() - claims.mfa_at <= window
    return {"operator": operator, "mfa_recent": bool(recent)}


class OrganizationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)           # the database function trims, collapses blanks and enforces 2-60
    admin_email: EmailStr
    admin_name: str | None = Field(default=None, max_length=200)


@router.post("/v1/platform/organizations", status_code=201)
def create_organization(body: OrganizationIn, response: Response, op: PlatformOperator = Depends(require_platform_operator(PERM))) -> dict:
    request_id = uuid4()
    response.headers["Cache-Control"] = "no-store"   # the body carries the one-time invite token
    try:
        with scoped_connection(get_engine(), user_id=op.id) as conn:
            res = conn.execute(
                text("SELECT public.platform_create_organization(:a, :n, :e, :d, :r)"),
                {"a": op.id, "n": body.name, "e": str(body.admin_email), "d": body.admin_name, "r": request_id},
            ).scalar_one()
            tenant_id = UUID(res["tenant_id"])
            # the route's half of the pair: inside the new organization's own row-level scope, in the same transaction as the function's `created`
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
            conn.execute(
                text("INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted) "
                     "VALUES (:t, :a, 'platform.organization.requested', 'tenant', :ti, CAST(:e AS jsonb))"),
                {"t": tenant_id, "a": op.id, "ti": str(tenant_id), "e": json.dumps({"request_id": str(request_id), "route": "POST /v1/platform/organizations"})},
            )
    except DBAPIError as exc:
        mapped = _map(exc)
        if mapped is None:
            raise
        raise mapped from exc
    inv = res["invite"]
    return {"tenant_id": str(tenant_id), "name": " ".join(body.name.split()), "request_id": str(request_id),
            "invite": {"id": inv["id"], "state": "pending", "role": inv["role"], "email": str(body.admin_email).strip().lower(), "expires_at": inv["expires_at"], "token": inv["token"]}}


@router.get("/v1/platform/organizations")
def list_organizations(response: Response, op: PlatformOperator = Depends(require_platform_operator(PERM))) -> dict:
    """Counts and labels only: never a row of an end customer, a subscriber, an OLT, an ONU or an Edge."""
    response.headers["Cache-Control"] = "no-store"
    try:
        with scoped_connection(get_engine(), user_id=op.id) as conn:
            rows = conn.execute(text("SELECT public.platform_list_organizations(:a)"), {"a": op.id}).scalar_one()
    except DBAPIError as exc:
        mapped = _map(exc)
        if mapped is None:
            raise
        raise mapped from exc
    return {"items": [{
        "id": r["tenant_id"], "name": r["name"], "status": r["status"], "created_at": r["created_at"], "edges": r["edges"], "olts": r["olts"], "onus": r["onus"],
        "created_by": r["created_by_name"], "created_via": r["created_via"], "invite_state": r["invite_state"], "api_trail": r["api_trail"],
    } for r in rows]}
