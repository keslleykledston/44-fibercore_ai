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
import logging
import time
from datetime import datetime
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, EmailStr, Field, StrictInt
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.deps import PLATFORM_MFA_MAX_SECONDS, PlatformOperator, assert_user_token_current, require_platform_operator
from app.core.db import get_engine, scoped_connection
from app.core.security import decode_token
from app.core.settings import Settings, get_settings

log = logging.getLogger(__name__)
router = APIRouter()
PERM = "platform:organizations"

# what the database function raises (message_primary) -> HTTP. Nothing else is ever echoed.
STATUS = {
    "platform_forbidden": (403, "forbidden"), "mfa_recent_required": (403, "mfa_recent_required"),
    "organization_name_taken": (409, "organization_name_taken"), "organization_rate_limited": (429, "organization_rate_limited"),
    "organization_name_invalid": (422, "organization_name_invalid"), "organization_email_invalid": (422, "organization_email_invalid"),
    "organization_admin_name_invalid": (422, "organization_admin_name_invalid"), "organization_cursor_invalid": (422, "organization_cursor_invalid"),
    # ADR-0047 (migration 0054)
    "organization_not_found": (404, "organization_not_found"), "organization_status_invalid": (422, "organization_status_invalid"),
    "organization_reason_invalid": (422, "organization_reason_invalid"), "feature_invalid": (422, "feature_invalid"), "feature_state_invalid": (422, "feature_state_invalid"),
    "limits_invalid": (422, "limits_invalid"),   # ADR-0047 D3 (migration 0055)
    "owner_only_feature": (403, "owner_only_feature"),   # the database refuses it too (migration 0054), not only the route
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
def list_organizations(response: Response, limit: int = Query(100, ge=1, le=200), before_at: datetime | None = None, before_id: UUID | None = None,
                       op: PlatformOperator = Depends(require_platform_operator(PERM))) -> dict:
    """Counts and labels only: never a row of an end customer, a subscriber, an OLT, an ONU or an Edge. Newest first, in pages by cursor: `next` says where the next page starts
    (null on the last) and `total` is every organization, so the list is never cut silently."""
    response.headers["Cache-Control"] = "no-store"
    if (before_at is None) != (before_id is None):
        raise HTTPException(422, "organization_cursor_invalid")
    try:
        with scoped_connection(get_engine(), user_id=op.id) as conn:
            res = conn.execute(text("SELECT public.platform_list_organizations(:a, :bt, :bi, :l)"), {"a": op.id, "bt": before_at, "bi": before_id, "l": limit}).scalar_one()
    except DBAPIError as exc:
        mapped = _map(exc)
        if mapped is None:
            raise
        raise mapped from exc
    return {"total": res["total"], "next": res["next"], "items": [{
        "id": r["tenant_id"], "name": r["name"], "status": r["status"], "created_at": r["created_at"], "edges": r["edges"], "olts": r["olts"], "onus": r["onus"],
        "edges_total": r["edges_total"], "edges_online": r["edges_online"], "olts_stale": r["olts_stale"], "last_heartbeat_at": r["last_heartbeat_at"], "flags_on": r["flags_on"],
        "created_by": r["created_by_name"], "created_via": r["created_via"], "invite_state": r["invite_state"], "api_trail": r["api_trail"],
    } for r in res["items"]]}



# ---- ADR-0047 fatia A: ciclo de vida, flags e detalhe -------------------------------------------------------------------------------------------------------------------------------

# Flags that WRITE to the network or hand decisions to an AI: the screen shows them and can switch them OFF (or back to the default, which is off), never ON. The owner's CLI turns them on.
OWNER_ONLY_FEATURES = frozenset({"bench_writes", "smart_diagnostics_active_tests", "smart_diagnostics_remediation", "quality_active_tests", "smart_diagnostics_copilot"})


class StatusIn(BaseModel):
    status: str = Field(pattern="^(active|suspended)$")
    reason: str = Field(min_length=1, max_length=400)       # the database function trims and enforces 3-200


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class FeatureIn(BaseModel):
    state: str = Field(pattern="^(on|off|default)$")
    reason: str = Field(min_length=1, max_length=400)


class LimitsIn(BaseModel):
    """Key present with a number = set; present with null = back to the code default; absent = untouched. The keys and ranges are checked by the database function too."""
    limits: dict[str, StrictInt | None] = Field(min_length=1, max_length=5)
    reason: str = Field(min_length=1, max_length=400)


def _call(op: PlatformOperator, kind: str, route: str, tenant_id: UUID, sql: str, params: dict, request_id: UUID, after=None) -> dict:
    """One platform change: the database function (the only writer), then, in the SAME transaction and inside the organization's own scope, the route's half of the audit pair."""
    try:
        with scoped_connection(get_engine(), user_id=op.id) as conn:
            res = conn.execute(text(sql), {"a": op.id, "t": tenant_id, "r": request_id, **params}).scalar_one()
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
            conn.execute(
                text("INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted) "
                     "VALUES (:t, :a, 'platform.change.requested', 'tenant', :ti, CAST(:e AS jsonb))"),
                {"t": tenant_id, "a": op.id, "ti": str(tenant_id), "e": json.dumps({"request_id": str(request_id), "kind": kind, "route": route})},
            )
            if after is not None:   # same transaction, organization scope already set: e.g. the notice e-mails (queued only if everything commits)
                try:
                    with conn.begin_nested():   # a failing notice must NEVER undo the change the operator asked for
                        after(conn, res)
                except Exception:   # noqa: BLE001
                    log.warning("platform change %s: the after-hook failed (change kept)", kind, exc_info=False)
    except DBAPIError as exc:
        mapped = _map(exc)
        if mapped is None:
            raise
        raise mapped from exc
    return res


@router.get("/v1/platform/organizations/{tenant_id}")
def organization_detail(tenant_id: UUID, response: Response, op: PlatformOperator = Depends(require_platform_operator(PERM))) -> dict:
    """State, health, flag overrides and the platform history of ONE organization. Counts and labels only (same rule as the list)."""
    response.headers["Cache-Control"] = "no-store"
    try:
        with scoped_connection(get_engine(), user_id=op.id) as conn:
            res = conn.execute(text("SELECT public.platform_organization_detail(:a, :t)"), {"a": op.id, "t": tenant_id}).scalar_one()
    except DBAPIError as exc:
        mapped = _map(exc)
        if mapped is None:
            raise
        raise mapped from exc
    from app.core.features import FEATURES
    over = {f["feature"]: f for f in res["features"]}
    res["catalog"] = [{"feature": name, "default": default, "enabled": over[name]["enabled"] if name in over else default, "source": "tenant" if name in over else "default",
                       "owner_only": name in OWNER_ONLY_FEATURES} for name, default in FEATURES.items()]
    res["unknown_overrides"] = sorted(n for n in over if n not in FEATURES)
    try:
        with scoped_connection(get_engine(), user_id=op.id) as conn:
            lim = conn.execute(text("SELECT public.platform_organization_limits(:a, :t)"), {"a": op.id, "t": tenant_id}).scalar_one()
    except DBAPIError as exc:
        mapped = _map(exc)
        if mapped is None:
            raise
        raise mapped from exc
    from app.core import limits as _limits
    dflt = _limits.defaults()
    values = {k: v for k, v in lim["limits"].items() if k != "updated_at"}
    res["limits"] = {"values": values, "defaults": dflt, "effective": {k: (values.get(k) if values.get(k) is not None else dflt[k]) for k in dflt},
                     "usage": lim["usage"], "updated_at": lim["limits"].get("updated_at")}
    res["history"] = sorted([*res["history"], *lim["history"]], key=lambda h: h["at"], reverse=True)[:60]
    return res


@router.post("/v1/platform/organizations/{tenant_id}/status")
def organization_status(tenant_id: UUID, body: StatusIn, response: Response, op: PlatformOperator = Depends(require_platform_operator(PERM))) -> dict:
    response.headers["Cache-Control"] = "no-store"
    from app.core import mail

    def notify(conn, res: dict) -> None:   # ADR-0048: tell the organization's administrators (no secret, no reason text: the reason is for the audit trail)
        if res.get("changed") and mail.enabled():
            kind = "organization_suspended" if body.status == "suspended" else "organization_reactivated"
            for to in mail.admin_addresses(conn, tenant_id):
                mail.queue_notice(conn, tenant_id, kind, to, op.id)
    return _call(op, "status", "POST /v1/platform/organizations/{id}/status", tenant_id, "SELECT public.platform_set_organization_status(:a, :t, :s, :why, :r)",
                 {"s": body.status, "why": body.reason}, uuid4(), after=notify)


@router.post("/v1/platform/organizations/{tenant_id}/rename")
def organization_rename(tenant_id: UUID, body: RenameIn, response: Response, op: PlatformOperator = Depends(require_platform_operator(PERM))) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return _call(op, "rename", "POST /v1/platform/organizations/{id}/rename", tenant_id, "SELECT public.platform_rename_organization(:a, :t, :n, :r)", {"n": body.name}, uuid4())


@router.put("/v1/platform/organizations/{tenant_id}/features/{feature}")
def organization_feature(tenant_id: UUID, feature: str, body: FeatureIn, response: Response, op: PlatformOperator = Depends(require_platform_operator(PERM))) -> dict:
    """Switch one flag of one organization. The catalog lives in code (the function only checks the shape): unknown name 422; the write-to-network flags (`OWNER_ONLY_FEATURES`) can be turned
    OFF here but never ON (403 `owner_only_feature`); a flag whose Edge-side support does not exist yet is refused exactly like the owner's CLI refuses it."""
    from app.core.features import FEATURES
    response.headers["Cache-Control"] = "no-store"
    if feature not in FEATURES:
        raise HTTPException(422, "unknown_feature")
    if body.state == "on":
        if feature in OWNER_ONLY_FEATURES:
            raise HTTPException(403, "owner_only_feature")
        if feature == "bench_writes":
            from app.core import bench
            if not bench.EDGE_SUPPORT:
                raise HTTPException(422, "feature_precondition")
        if feature == "olt_query":
            from app.core import olt_query
            if not olt_query.EDGE_SUPPORT:
                raise HTTPException(422, "feature_precondition")
    return _call(op, "feature", "PUT /v1/platform/organizations/{id}/features/{feature}", tenant_id,
                 "SELECT public.platform_set_feature(:a, :t, :f, :s, :why, :r)", {"f": feature, "s": body.state, "why": body.reason}, uuid4())


@router.put("/v1/platform/organizations/{tenant_id}/limits")
def organization_limits(tenant_id: UUID, body: LimitsIn, response: Response, op: PlatformOperator = Depends(require_platform_operator(PERM))) -> dict:
    """ADR-0047 D3: technical limits of ONE organization (Edges, OLTs, members, intake budget). Server protection, not billing. Lowering a limit below the current use only stops NEW
    creations; nothing existing is removed or blocked. Unknown key or out-of-range value 422 `limits_invalid`."""
    response.headers["Cache-Control"] = "no-store"
    return _call(op, "limits", "PUT /v1/platform/organizations/{id}/limits", tenant_id, "SELECT public.platform_set_limits(:a, :t, CAST(:l AS jsonb), :why, :r)",
                 {"l": json.dumps(body.limits), "why": body.reason}, uuid4())
