"""ERP Hub, connections (ADR-0033): register a HubSoft connection, test it, enable/disable it. READ-ONLY toward the ERP; nothing here writes to it.

A connection holds the instance URL and the NAME of a secret (never the secret). `test` authenticates and nothing else. While the tenant flag `erp_hubsoft` is off,
every call is refused with `feature_disabled`. IXC and SGP are in the registry but have no connector: a connection for them cannot be created."""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import erp_hub, features
from app.core.db import get_engine, scoped_connection
from app.core.settings import Settings, get_settings
from app.integrations import hubsoft

router = APIRouter()
log = logging.getLogger("fibercore.erp")

TEST_MIN_INTERVAL_S = 10   # one test of a connection per 10 s: the vendor's auth limit is per IP and shared
_LIMITERS: dict[UUID, tuple[hubsoft.RateLimiter, hubsoft.RateLimiter]] = {}   # per connection, process-wide: a new HTTP request must not reset the budget


def _resolve(host: str) -> list[str]:   # replaced by the tests
    return erp_hub.resolve_public(host)


def _send_for(host: str, addresses: list[str]) -> hubsoft.Send:   # replaced by the tests
    return hubsoft.make_send(host, addresses)


def _auth_gate(cap: int):
    """The deployment-wide authentication budget: the vendor's limit is per egress IP, so it cannot live in one process or one connection. One atomic increment per
    send in a short transaction of its own (no row lock is held while the request runs); a full minute refuses."""
    def gate() -> None:
        with get_engine().begin() as c:
            row = c.execute(
                text("INSERT INTO erp_egress_budget (scope, bucket, n) VALUES ('hubsoft.auth', date_trunc('minute', now()), 1) "
                     "ON CONFLICT (scope, bucket) DO UPDATE SET n = erp_egress_budget.n + 1 WHERE erp_egress_budget.n < :cap RETURNING n"), {"cap": cap}).first()
            if row is None:
                wait = c.execute(text("SELECT EXTRACT(EPOCH FROM (date_trunc('minute', now()) + interval '1 minute' - now()))")).scalar()
            else:
                c.execute(text("DELETE FROM erp_egress_budget WHERE bucket < now() - interval '1 hour'"))
        if row is None:
            raise hubsoft.HubSoftError(hubsoft.RATE_LIMITED, retry_after=float(wait or 60))
    return gate


def _client_options() -> dict:   # replaced by the tests (a fake sleep: the retry waits are real time otherwise)
    return {}


class ConnectionIn(BaseModel):
    provider: str = Field(max_length=20)
    display_name: str = Field(min_length=1, max_length=120)
    auth_profile: str = Field(max_length=40)
    base_url: str = Field(max_length=300)
    secret_ref: str = Field(max_length=64)
    transport_mode: str = Field(default="cloud", max_length=10)
    sync_mode: str = Field(default="lookup_only", max_length=20)


def _view(r) -> dict:
    return {"id": str(r.id), "provider": r.provider, "display_name": r.display_name, "auth_profile": r.auth_profile, "transport_mode": r.transport_mode,
            "sync_mode": r.sync_mode, "host": r.base_url.removeprefix("https://"), "enabled": r.enabled, "status": r.status,
            "last_tested_at": r.last_tested_at.isoformat() if r.last_tested_at else None, "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
            "last_error_class": r.last_error_class, "integration_status": erp_hub.PROVIDERS[r.provider].integration_status}


_COLS = "id, provider, display_name, auth_profile, transport_mode, sync_mode, base_url, secret_ref, enabled, status, last_tested_at, last_success_at, last_error_class"


def _get(conn: Connection, connection_id: UUID):
    r = conn.execute(text(f"SELECT {_COLS} FROM erp_connections WHERE id = :i"), {"i": connection_id}).first()  # noqa: S608
    if r is None:
        raise HTTPException(404, "connection not found")
    return r


def _feature(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "erp_hubsoft")


@router.get("/v1/integrations/erp")
def list_connections(p: Principal = Depends(require("erp:test")), conn: Connection = TENANT_CONN) -> dict:
    on = features.enabled(conn, p.tenant_id, "erp_hubsoft")
    rows = conn.execute(text(f"SELECT {_COLS} FROM erp_connections ORDER BY created_at, id")).all()  # noqa: S608
    return {"enabled": on, "homologation_order": list(erp_hub.HOMOLOGATION_ORDER),
            "providers": [{"id": q.id, "label": q.label, "priority": q.priority, "available": q.real_connector, "integration_status": q.integration_status,
                           "auth_profiles": list(q.auth_profiles), "sync_modes": list(q.sync_modes)} for q in erp_hub.PROVIDERS.values()],
            "items": [_view(r) for r in rows]}


@router.post("/v1/integrations/erp", status_code=201)
def create_connection(body: ConnectionIn, p: Principal = Depends(require("erp:manage")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)) -> dict:
    _feature(conn, p)
    try:
        erp_hub.validate_connection(body.provider, body.auth_profile, body.transport_mode, body.sync_mode, body.secret_ref)
        url = erp_hub.normalize_base_url(body.base_url, erp_hub.parse_allowed_hosts(settings.erp_allowed_hosts))
    except erp_hub.ConnectionInvalid as e:
        raise HTTPException(422, str(e)) from None
    exists = conn.execute(text("SELECT 1 FROM erp_connections WHERE display_name = :n"), {"n": body.display_name}).first()
    if exists is not None:
        raise HTTPException(409, "display_name_in_use")
    r = conn.execute(
        text("INSERT INTO erp_connections (tenant_id, provider, display_name, auth_profile, transport_mode, sync_mode, base_url, secret_ref, created_by) "
             "VALUES (:t, :p, :n, :a, :m, :s, :u, :r, :by) RETURNING " + _COLS),
        {"t": p.tenant_id, "p": body.provider, "n": body.display_name, "a": body.auth_profile, "m": body.transport_mode, "s": body.sync_mode, "u": url,
         "r": body.secret_ref, "by": p.id}).first()
    audit(conn, p, "erp.connection.created", "erp_connection", str(r.id), {"provider": body.provider, "host": url.removeprefix("https://")})
    return _view(r)


@router.post("/v1/integrations/erp/{connection_id}/test")
def test_connection(connection_id: UUID, p: Principal = Depends(require("erp:test")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)) -> dict:
    """Authenticates against the instance (token only). 200 with the outcome either way: a failed test is a result, not an error of this call."""
    _feature(conn, p)
    c = _get(conn, connection_id)
    prov = erp_hub.PROVIDERS[c.provider]
    if not prov.real_connector:
        raise HTTPException(403, "provider_not_available")
    if c.status == "disabled":
        raise HTTPException(409, "connection_disabled")   # a disabled connection is final: the kill switch is not undone by a test
    # The row is claimed in a SHORT transaction of its own and committed BEFORE any network I/O, and the outcome is written in another one: no row lock is held while
    # the ERP is slow, so `disable` (the kill switch) is never queued behind a test.
    with scoped_connection(get_engine(), user_id=p.id, tenant_id=p.tenant_id) as short:
        claimed = short.execute(
            text("UPDATE erp_connections SET last_tested_at = now() WHERE id = :i AND status <> 'disabled' "
                 "AND (last_tested_at IS NULL OR last_tested_at < now() - make_interval(secs => :s)) RETURNING id"),
            {"i": connection_id, "s": TEST_MIN_INTERVAL_S}).first()
    if claimed is None:
        raise HTTPException(429, "test_too_soon")
    error: str | None = None
    state = "healthy"
    try:
        host = c.base_url.removeprefix("https://")
        erp_hub.normalize_base_url(c.base_url, erp_hub.parse_allowed_hosts(settings.erp_allowed_hosts))   # the allowlist is re-checked on every use, not only at creation
        creds = erp_hub.load_credentials(settings.erp_secrets_dir, p.tenant_id, c.secret_ref)
        addrs = _resolve(host)
        lim = _LIMITERS.setdefault(connection_id, (hubsoft.RateLimiter(hubsoft.Policy().request_per_second, hubsoft.Policy().request_burst),
                                                  hubsoft.RateLimiter(hubsoft.Policy().auth_per_minute / 60.0, hubsoft.Policy().auth_burst)))
        key = (str(p.tenant_id), str(connection_id), host, creds.version)   # tokens are never shared between tenants, connections, hosts or credential versions
        client = hubsoft.HubSoftClient(creds=creds, key=key, send=_send_for(host, addrs), limiter=lim[0], auth_limiter=lim[1], auth_gate=_auth_gate(settings.erp_auth_per_minute), **_client_options())
        hubsoft.test_connection(client)
    except erp_hub.SecretError as e:
        error, state = e.code.upper(), "unconfigured"
    except erp_hub.ConnectionInvalid as e:
        error, state = e.args[0].upper(), "degraded"
    except hubsoft.HubSoftError as e:
        error, state = e.code, e.state
    log.info("erp test connection=%s provider=%s result=%s", connection_id, c.provider, error or "ok")   # class only: no host, no body, no secret
    with scoped_connection(get_engine(), user_id=p.id, tenant_id=p.tenant_id) as short:
        short.execute(
            text("UPDATE erp_connections SET status = :s, last_error_class = CAST(:e AS text), updated_at = now(), enabled = (enabled AND :s = 'healthy'), "
                 "last_success_at = CASE WHEN CAST(:e AS text) IS NULL THEN now() ELSE last_success_at END WHERE id = :i AND status <> 'disabled'"),   # never undo a disable that came meanwhile
            {"s": state, "e": error, "i": connection_id})
        audit(short, p, "erp.connection.tested", "erp_connection", str(connection_id), {"ok": error is None, "error_class": error})
    return _view(_get(conn, connection_id))


@router.post("/v1/integrations/erp/{connection_id}/enable")
def enable_connection(connection_id: UUID, p: Principal = Depends(require("erp:manage")), conn: Connection = TENANT_CONN) -> dict:
    """Only a connection whose last test succeeded may be enabled."""
    _feature(conn, p)
    _get(conn, connection_id)   # 404 for an unknown or foreign connection
    done = conn.execute(text("UPDATE erp_connections SET enabled = true, updated_at = now() WHERE id = :i AND status = 'healthy' RETURNING id"), {"i": connection_id}).first()
    if done is None:   # one atomic statement: a disable or a failed test that lands first leaves nothing to enable
        raise HTTPException(409, "test_first")
    audit(conn, p, "erp.connection.enabled", "erp_connection", str(connection_id), {})
    return _view(_get(conn, connection_id))


@router.post("/v1/integrations/erp/{connection_id}/disable")
def disable_connection(connection_id: UUID, p: Principal = Depends(require("erp:manage")), conn: Connection = TENANT_CONN) -> dict:
    """Allowed even with the flag off (a kill switch must always work); it keeps the row and its history."""
    _get(conn, connection_id)
    conn.execute(text("UPDATE erp_connections SET enabled = false, status = 'disabled', updated_at = now() WHERE id = :i"), {"i": connection_id})
    audit(conn, p, "erp.connection.disabled", "erp_connection", str(connection_id), {})
    return _view(_get(conn, connection_id))
