"""Outbound webhooks of the organization (ADR-0051 D2): an administrator registers an https endpoint and picks events from a CLOSED catalog; the dispatcher worker signs and delivers.

The signing secret is shown ONCE (at creation and at rotation) and stored encrypted; the application cannot read it back. The platform never sends end-customer data: an event carries ids and
counts from a fixed list of keys. Failing endpoints turn themselves off after 10 failures in a row.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import webhooks
from app.core.settings import Settings, get_settings

router = APIRouter()


class EndpointIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    url: str = Field(min_length=10, max_length=500)
    events: list[str] = Field(min_length=1, max_length=len(webhooks.EVENTS))


class EndpointPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    events: list[str] | None = Field(default=None, min_length=1, max_length=len(webhooks.EVENTS))
    active: bool | None = None


def _need_key(settings: Settings) -> None:
    if not webhooks.available(settings):
        raise HTTPException(503, "webhooks_unavailable")   # fail closed: no encryption key, no secrets, no endpoints


def _events(events: list[str]) -> list[str]:
    ev = sorted(set(events))
    if any(e not in webhooks.EVENTS for e in ev):
        raise HTTPException(422, "event_not_allowed")
    return ev


def _view(r) -> dict:
    return {"id": str(r.id), "name": r.name, "url": r.url, "events": list(r.events), "active": r.active, "consecutive_failures": r.consecutive_failures,
            "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None, "last_failure_at": r.last_failure_at.isoformat() if r.last_failure_at else None,
            "disabled_reason": r.disabled_reason, "created_at": r.created_at.isoformat()}


COLS = "id, name, url, events, active, consecutive_failures, last_success_at, last_failure_at, disabled_reason, created_at"


@router.get("/v1/webhooks")
def list_webhooks(p: Principal = Depends(require("webhooks:manage")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)) -> dict:
    rows = conn.execute(text(f"SELECT {COLS} FROM webhook_endpoints ORDER BY created_at DESC")).all()   # noqa: S608 - fixed columns
    return {"items": [_view(r) for r in rows], "events": list(webhooks.EVENTS), "available": webhooks.available(settings), "max_endpoints": webhooks.MAX_ENDPOINTS}


@router.post("/v1/webhooks", status_code=201)
def create_webhook(body: EndpointIn, p: Principal = Depends(require("webhooks:manage")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)) -> dict:
    _need_key(settings)
    ev = _events(body.events)
    problem = webhooks.url_problem(body.url)
    if problem:
        raise HTTPException(422, problem)
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"webhooks:{p.tenant_id}"})
    if conn.execute(text("SELECT count(*) FROM webhook_endpoints")).scalar_one() >= webhooks.MAX_ENDPOINTS:
        raise HTTPException(409, "webhook_limit")
    secret = webhooks.new_secret()
    wid = uuid4()
    conn.execute(text("INSERT INTO webhook_endpoints (tenant_id, id, name, url, secret_enc, events, created_by) VALUES (:t, :i, :n, :u, :s, :e, :c)"),
                 {"t": p.tenant_id, "i": wid, "n": " ".join(body.name.split()), "u": body.url, "s": webhooks.encrypt_secret(settings, secret), "e": ev, "c": p.id})
    audit(conn, p, "webhook.created", "webhook", str(wid), {"name": " ".join(body.name.split()), "events": ev})      # the URL and the secret are NOT in the trail
    return {"id": str(wid), "secret": secret, "events": ev, "signature_header": webhooks.SIGNATURE_HEADER}


def _own(conn: Connection, wid: UUID):
    row = conn.execute(text(f"SELECT {COLS} FROM webhook_endpoints WHERE id = :i"), {"i": wid}).first()   # noqa: S608
    if row is None:
        raise HTTPException(404, "webhook_not_found")
    return row


@router.patch("/v1/webhooks/{webhook_id}")
def patch_webhook(webhook_id: UUID, body: EndpointPatch, p: Principal = Depends(require("webhooks:manage")), conn: Connection = TENANT_CONN) -> dict:
    cur = _own(conn, webhook_id)
    sets, args = [], {"i": webhook_id}
    if body.name is not None:
        sets.append("name = :n"); args["n"] = " ".join(body.name.split())
    if body.events is not None:
        sets.append("events = :e"); args["e"] = _events(body.events)
    if body.active is not None:
        sets.append("active = :a"); args["a"] = body.active
        if body.active:
            sets.append("consecutive_failures = 0, disabled_at = NULL, disabled_reason = NULL")
    if not sets:
        raise HTTPException(422, "nothing_to_change")
    conn.execute(text("UPDATE webhook_endpoints SET " + ", ".join(sets) + " WHERE id = :i"), args)   # noqa: S608 - fixed fragments
    audit(conn, p, "webhook.updated", "webhook", str(webhook_id), {"active": body.active, "events": args.get("e"), "was_active": cur.active})
    return _view(_own(conn, webhook_id))


@router.delete("/v1/webhooks/{webhook_id}")
def delete_webhook(webhook_id: UUID, p: Principal = Depends(require("webhooks:manage")), conn: Connection = TENANT_CONN) -> dict:
    _own(conn, webhook_id)
    conn.execute(text("DELETE FROM webhook_endpoints WHERE id = :i"), {"i": webhook_id})
    audit(conn, p, "webhook.deleted", "webhook", str(webhook_id), {})
    return {"deleted": True}


@router.post("/v1/webhooks/{webhook_id}/rotate-secret")
def rotate_secret(webhook_id: UUID, p: Principal = Depends(require("webhooks:manage")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)) -> dict:
    _need_key(settings)
    _own(conn, webhook_id)
    secret = webhooks.new_secret()
    conn.execute(text("UPDATE webhook_endpoints SET secret_enc = :s WHERE id = :i"), {"s": webhooks.encrypt_secret(settings, secret), "i": webhook_id})
    audit(conn, p, "webhook.secret_rotated", "webhook", str(webhook_id), {})
    return {"secret": secret}


@router.post("/v1/webhooks/{webhook_id}/test", status_code=202)
def test_webhook(webhook_id: UUID, p: Principal = Depends(require("webhooks:manage")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)) -> dict:
    """Queue one `webhook.test` delivery (a fixed, harmless payload). The dispatcher sends it like any other; read the result in the delivery list."""
    _need_key(settings)
    _own(conn, webhook_id)
    eid = uuid4()
    conn.execute(
        text("INSERT INTO webhook_deliveries (tenant_id, endpoint_id, event_id, event_type, payload, expires_at) VALUES (:t, :w, :e, 'webhook.test', CAST(:b AS jsonb), now() + interval '1 hour')"),
        {"t": p.tenant_id, "w": webhook_id, "e": eid, "b": '{"id": "%s", "type": "webhook.test", "organization_id": "%s", "data": {"message": "teste de entrega"}}' % (eid, p.tenant_id)})
    audit(conn, p, "webhook.test_queued", "webhook", str(webhook_id), {})
    return {"queued": True, "event_id": str(eid)}


@router.get("/v1/webhooks/{webhook_id}/deliveries")
def deliveries(webhook_id: UUID, p: Principal = Depends(require("webhooks:manage")), conn: Connection = TENANT_CONN) -> dict:
    _own(conn, webhook_id)
    rows = conn.execute(
        text("SELECT id, event_type, created_at, attempts, sent_at, failed_at, last_status, last_error FROM webhook_deliveries WHERE endpoint_id = :i ORDER BY created_at DESC LIMIT 50"),
        {"i": webhook_id}).all()
    return {"items": [{"id": str(r.id), "event_type": r.event_type, "created_at": r.created_at.isoformat(), "attempts": r.attempts, "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                       "failed_at": r.failed_at.isoformat() if r.failed_at else None, "last_status": r.last_status, "last_error": r.last_error,
                       "state": "sent" if r.sent_at else ("failed" if r.failed_at else "pending")} for r in rows]}
