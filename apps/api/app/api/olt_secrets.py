"""OLT credentials typed on the screen, sealed in the browser and opened only by the Edge (ADR-0045).

The Cloud NEVER sees a credential in clear: the browser seals it with the Edge's public key (ECDH P-256 + HKDF + AES-256-GCM) and this module stores and forwards the CIPHERTEXT. Nothing here can open a blob (no private key exists
on this side), no response to a person ever returns a blob (not even sealed), and neither the audit log nor any log line carries a blob, a kind's content, an address or a name of a secret.

Two audiences, one module:
* the Edge (service account bound to one Edge): publish its seal key, take the next delivery (a lease: one in flight per Edge, serialised by an advisory lock and by a partial unique index), report the result;
* the person (`fleet:secrets`, only `isp_admin`; tenant flag `fleet_secrets`, OFF by default): see and confirm the Edge's key fingerprint, post a sealed delivery, list the state of the last ones.
The blob is readable by the application role only through the SECURITY DEFINER function `app_secret_delivery_blob` (migration 0050) and only from `next_delivery` below; a test keeps it that way.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import TENANT_CONN, Principal, edge_ingest_limit, require
from app.api.routes import audit
from app.core import features, jobsign, olt_secrets
from app.core.settings import Settings, get_settings

log = logging.getLogger(__name__)
router = APIRouter()
FLAG = "fleet_secrets"
HISTORY = 10


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, FLAG)


def _person(p: Principal = Depends(require("fleet:secrets")), conn: Connection = TENANT_CONN) -> Principal:
    """Permission, THEN the tenant flag, before the body is even validated: with `fleet_secrets` off every person route answers 403 `feature_disabled`, whatever was sent (and an unauthorised caller learns nothing)."""
    _flag(conn, p)
    return p


def _edge(p: Principal) -> UUID:
    if p.edge_id is None:
        raise HTTPException(403, "token is not bound to an edge")
    return p.edge_id


# ============================================================ the Edge side ==
class SealKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_key: str = Field(min_length=80, max_length=100)   # 65 bytes -> 87 base64url characters

    @field_validator("public_key")
    @classmethod
    def _point(cls, v: str) -> str:
        try:
            olt_secrets.parse_public_key(v)
        except ValueError as exc:
            raise ValueError("public_key must be the base64url of an uncompressed P-256 point") from exc   # never echoes the value
        return v


@router.post("/v1/edge/seal-key")
def report_seal_key(body: SealKeyIn, p: Principal = Depends(require("jobs:execute")), _rl: None = Depends(edge_ingest_limit), conn: Connection = TENANT_CONN) -> dict:
    """The Edge publishes its seal public key (idempotent). A NEW value means `pending` again (a person must confirm the fingerprint) and cancels what was waiting under the old key."""
    edge_id = _edge(p)
    cur = conn.execute(text("SELECT status, seal_public_key, seal_key_id, seal_key_state FROM edges WHERE id = :e FOR UPDATE"), {"e": edge_id}).first()
    if cur is None:
        raise HTTPException(404, "edge not found")
    if cur.status == "revoked":
        raise HTTPException(403, "edge revoked")
    point = olt_secrets.parse_public_key(body.public_key)
    kid = olt_secrets.key_id(point)
    if cur.seal_public_key == body.public_key:
        return {"key_id": cur.seal_key_id, "state": cur.seal_key_state}
    conn.execute(text("UPDATE edges SET seal_public_key = :k, seal_key_id = :i, seal_key_state = 'pending', seal_key_reported_at = now(), seal_key_confirmed_by = NULL, seal_key_confirmed_at = NULL WHERE id = :e"),
                 {"k": body.public_key, "i": kid, "e": edge_id})
    cancelled = conn.execute(text("UPDATE olt_secret_deliveries SET status = 'CANCELLED', code = 'key_changed', sealed = NULL, updated_at = now() "
                                  "WHERE edge_id = :e AND status IN ('PENDING', 'DISPATCHED')"), {"e": edge_id}).rowcount
    audit(conn, p, "fleet.edge.seal_key.reported", "edge", str(edge_id), {"key_id": kid, "previous_key_id": cur.seal_key_id, "cancelled_deliveries": cancelled})
    return {"key_id": kid, "state": "pending"}


def _lapsed_leases(conn: Connection, edge_id: UUID) -> None:
    """A lease that ran out with no result: back to PENDING (attempts + 1), or FAILED `lease_exhausted` (blob erased) past MAX_ATTEMPTS. Runs under the per-Edge advisory lock."""
    rows = conn.execute(text("SELECT id, attempts FROM olt_secret_deliveries WHERE edge_id = :e AND status = 'DISPATCHED' AND lease_until <= now() ORDER BY created_at FOR UPDATE"), {"e": edge_id}).all()
    for r in rows:
        if r.attempts + 1 > olt_secrets.MAX_ATTEMPTS:
            conn.execute(text("UPDATE olt_secret_deliveries SET status = 'FAILED', code = 'lease_exhausted', attempts = attempts + 1, sealed = NULL, updated_at = now() WHERE id = :i"), {"i": r.id})
        else:
            conn.execute(text("UPDATE olt_secret_deliveries SET status = 'PENDING', attempts = attempts + 1, lease_token = NULL, lease_until = NULL, updated_at = now() WHERE id = :i"), {"i": r.id})


def _in_flight(conn: Connection, edge_id: UUID):
    """The delivery already leased to this Edge, row-locked: a concurrent `result` (which locks the same row) either finished before this read (then the row is no longer DISPATCHED and is skipped) or waits for this transaction."""
    return conn.execute(text("SELECT id, lease_token, olt_name, kind, key_id, expires_at, tenant_id FROM olt_secret_deliveries "
                             "WHERE edge_id = :e AND status = 'DISPATCHED' AND lease_until > now() AND expires_at > now() FOR UPDATE"), {"e": edge_id}).first()


def _grant(conn: Connection, edge_id: UUID, key_id: str):
    """The oldest PENDING delivery for the Edge's CURRENT key becomes DISPATCHED with a fresh lease token, in this transaction. SKIP LOCKED: a row someone else holds is not waited for."""
    row = conn.execute(text("SELECT id FROM olt_secret_deliveries WHERE edge_id = :e AND status = 'PENDING' AND key_id = :k AND expires_at > now() ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED"),
                       {"e": edge_id, "k": key_id}).first()
    if row is None:
        return None
    return conn.execute(text("UPDATE olt_secret_deliveries SET status = 'DISPATCHED', lease_token = :t, lease_until = now() + make_interval(secs => :s), updated_at = now() WHERE id = :i "
                             "RETURNING id, lease_token, olt_name, kind, key_id, expires_at, tenant_id"), {"t": uuid4(), "s": olt_secrets.LEASE_SECONDS, "i": row.id}).first()


def _envelope(conn: Connection, p: Principal, edge_id: UUID, row, settings: Settings) -> dict:
    blob = conn.execute(text("SELECT app_secret_delivery_blob(:i, :l)"), {"i": row.id, "l": row.lease_token}).scalar()
    if blob is None:   # cannot happen inside one transaction that just leased it: a defect, never an unsigned or empty answer
        raise HTTPException(503, "blob_unavailable", headers={"Retry-After": "5"})
    blob = bytes(blob)
    expires_unix = int(row.expires_at.timestamp())
    aad = olt_secrets.aad(tenant_id=row.tenant_id, edge_id=edge_id, olt_name=row.olt_name, kind=row.kind, delivery_id=row.id, key_id_=row.key_id, expires_at_unix=expires_unix)
    sig = olt_secrets.sign_delivery(jobsign.load_private(settings.job_signing_key), aad, blob)
    return {"id": str(row.id), "lease_token": str(row.lease_token), "olt_name": row.olt_name, "kind": row.kind, "key_id": row.key_id, "expires_at": expires_unix,
            "sealed": olt_secrets.b64url_encode(blob), "signature": sig}


@router.get("/v1/edge/secret-deliveries/next")
def next_delivery(response: Response, p: Principal = Depends(require("jobs:execute")), conn: Connection = TENANT_CONN, settings: Settings = Depends(get_settings)):
    """The next sealed delivery for THIS Edge, or 204. One in flight per Edge: a second call while a lease is valid gets the SAME delivery and lease_token back (a retry after a lost response is safe)."""
    edge_id = _edge(p)
    if not settings.job_signing_key:
        raise HTTPException(503, "job signing key not configured")   # fail closed: nothing is dispatched unsigned
    if not features.enabled(conn, p.tenant_id, FLAG):   # flag off: nothing is dispatched (the sweeper still erases what was waiting)
        response.status_code = 204
        return None
    jobsign.load_private(settings.job_signing_key)   # a malformed key is a 5xx before anything is leased
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('olt_secret_next|' || CAST(:e AS text), 0))"), {"e": edge_id})   # serialised per Edge: two polls never race the unique index
    edge = conn.execute(text("SELECT seal_key_id, seal_key_state FROM edges WHERE id = :e FOR SHARE"), {"e": edge_id}).first()
    if edge is None:
        raise HTTPException(404, "edge not found")
    conn.execute(text("UPDATE olt_secret_deliveries SET status = 'EXPIRED', sealed = NULL, updated_at = now() WHERE edge_id = :e AND status IN ('PENDING', 'DISPATCHED') AND expires_at <= now()"), {"e": edge_id})
    row = _in_flight(conn, edge_id)
    if row is None:
        _lapsed_leases(conn, edge_id)
        if edge.seal_key_state != "confirmed":   # an unconfirmed key is not trusted: nothing is handed out (and a key change already cancelled what waited)
            response.status_code = 204
            return None
        try:
            with conn.begin_nested():
                row = _grant(conn, edge_id, edge.seal_key_id)
        except IntegrityError as exc:   # the partial unique index refused a second DISPATCHED: a defect, not the normal flow (the advisory lock prevents it)
            log.error("secret delivery dispatch refused by the one-in-flight index (edge %s)", edge_id)
            raise HTTPException(503, "dispatch_conflict", headers={"Retry-After": "5"}) from exc
    if row is None:
        response.status_code = 204
        return None
    return _envelope(conn, p, edge_id, row, settings)


class ResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_token: UUID
    outcome: Literal["applied", "failed"]
    code: str | None = Field(None, max_length=32)

    @model_validator(mode="after")
    def _code(self):
        if self.outcome == "applied" and self.code is not None:
            raise ValueError("code is only for outcome failed")
        if self.outcome == "failed" and self.code not in olt_secrets.RESULT_CODES:
            raise ValueError("code must be one of the documented failure codes")
        return self


@router.post("/v1/edge/secret-deliveries/{delivery_id}/result", status_code=204)
def delivery_result(delivery_id: UUID, body: ResultIn, p: Principal = Depends(require("jobs:execute")), conn: Connection = TENANT_CONN) -> Response:
    """Only the CURRENT, unexpired lease token of a DISPATCHED delivery moves it (409 `stale_lease` otherwise, nothing changed). The same result repeated in a terminal state is 204; a different one is 409. Every terminal state erases the blob."""
    edge_id = _edge(p)
    row = conn.execute(text("SELECT id, status, lease_token, code, kind, olt_id, (lease_until IS NOT NULL AND lease_until > now()) AS live FROM olt_secret_deliveries WHERE id = :i AND edge_id = :e FOR UPDATE"),
                       {"i": delivery_id, "e": edge_id}).first()
    if row is None:
        raise HTTPException(404, "delivery not found")
    status = "APPLIED" if body.outcome == "applied" else "FAILED"
    if row.status == "DISPATCHED":
        if row.lease_token != body.lease_token or not row.live:   # the CURRENT attempt only: a lease that ran out is not current even if no `next` has reconciled it yet (the redelivery is idempotent at the Edge: it reports `applied` again)
            raise HTTPException(409, "stale_lease")
        conn.execute(text("UPDATE olt_secret_deliveries SET status = :s, code = :c, sealed = NULL, updated_at = now() WHERE id = :i"), {"s": status, "c": body.code, "i": delivery_id})
        audit(conn, p, "fleet.secret_delivery.result", "olt", str(row.olt_id), {"delivery_id": str(delivery_id), "kind": row.kind, "outcome": body.outcome, "code": body.code})
        return Response(status_code=204)
    if row.status == "PENDING" or row.lease_token != body.lease_token:
        raise HTTPException(409, "stale_lease")
    if row.status == status and row.code == body.code:
        return Response(status_code=204)   # the same result again (a retry after a lost answer): nothing changes
    raise HTTPException(409, "result_conflict")


# ============================================================ the person side ==
def _key_view(r, now: datetime) -> dict:
    point = olt_secrets.b64url_decode(r.seal_public_key) if r.seal_public_key else None
    # tenant_id and edge_id are what the browser puts in the AAD (the Edge checks them against its own configuration)
    return {"tenant_id": str(r.tenant_id), "edge_id": str(r.id), "edge_name": r.name, "state": r.seal_key_state or "none", "key_id": r.seal_key_id, "public_key": r.seal_public_key,
            "fingerprint": olt_secrets.fingerprint(point) if point else None,
            "reported_at": r.seal_key_reported_at.isoformat() if r.seal_key_reported_at else None,
            "confirmed_at": r.seal_key_confirmed_at.isoformat() if r.seal_key_confirmed_at else None,
            "server_time": int(now.timestamp()), "max_window_seconds": olt_secrets.MAX_WINDOW_SECONDS}


_KEY_SQL = "SELECT tenant_id, id, name, seal_public_key, seal_key_id, seal_key_state, seal_key_reported_at, seal_key_confirmed_at FROM edges WHERE id = :e"


@router.get("/v1/fleet/edges/{edge_id}/seal-key")
def get_seal_key(edge_id: UUID, p: Principal = Depends(_person), conn: Connection = TENANT_CONN) -> dict:
    r = conn.execute(text(_KEY_SQL), {"e": edge_id}).first()
    if r is None:
        raise HTTPException(404, "edge not found")
    return _key_view(r, conn.execute(text("SELECT now()")).scalar())


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    fingerprint: str = Field(min_length=1, max_length=64)


@router.post("/v1/fleet/edges/{edge_id}/seal-key/confirm")
def confirm_seal_key(edge_id: UUID, body: ConfirmIn, p: Principal = Depends(_person), conn: Connection = TENANT_CONN) -> dict:
    """A person compares the fingerprint the screen shows with the one the Edge host prints (`fibercore-edge seal-fingerprint`) and types it. Only then is the key trusted."""
    r = conn.execute(text(_KEY_SQL + " FOR UPDATE"), {"e": edge_id}).first()
    if r is None:
        raise HTTPException(404, "edge not found")
    if r.seal_key_id is None:
        raise HTTPException(409, "no_seal_key")
    if r.seal_key_id != body.key_id:
        raise HTTPException(409, "seal_key_changed")   # the Edge published another key while the person was looking
    if not olt_secrets.fingerprint_matches(body.fingerprint, olt_secrets.b64url_decode(r.seal_public_key)):
        raise HTTPException(422, "fingerprint_mismatch")
    if r.seal_key_state != "confirmed":
        conn.execute(text("UPDATE edges SET seal_key_state = 'confirmed', seal_key_confirmed_by = :u, seal_key_confirmed_at = now() WHERE id = :e AND seal_key_id = :k"), {"u": p.id, "e": edge_id, "k": body.key_id})
        audit(conn, p, "fleet.edge.seal_key.confirmed", "edge", str(edge_id), {"key_id": body.key_id})
    return _key_view(conn.execute(text(_KEY_SQL), {"e": edge_id}).one(), conn.execute(text("SELECT now()")).scalar())


class DeliveryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery_id: UUID
    kind: Literal["ssh_login", "snmp_community"]
    key_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    expires_at: int = Field(strict=True, gt=0, lt=10**11)   # unix seconds: the same integer that enters the AAD
    sealed: str = Field(min_length=100, max_length=olt_secrets.MAX_BLOB_CHARS)

    @field_validator("sealed")
    @classmethod
    def _blob(cls, v: str) -> str:
        try:
            olt_secrets.parse_blob(v)
        except ValueError as exc:
            raise ValueError("sealed is not a valid sealed blob") from exc   # never echoes the value
        return v


def _delivery_row(r) -> dict:
    return {"id": str(r.id), "kind": r.kind, "status": r.status, "code": r.code, "key_id": r.key_id, "expires_at": int(r.expires_at.timestamp()),
            "expires_at_iso": r.expires_at.isoformat(), "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(), "attempts": r.attempts}   # NEVER the blob, not even sealed


@router.post("/v1/fleet/olts/{olt_id}/secret-deliveries", status_code=202)
def create_delivery(olt_id: UUID, body: DeliveryIn, p: Principal = Depends(_person), conn: Connection = TENANT_CONN) -> dict:
    olt = conn.execute(text("SELECT id, name, edge_id, snmp_version FROM olts WHERE id = :i FOR UPDATE"), {"i": olt_id}).first()   # the lock also serialises the per-OLT cap below
    if olt is None:
        raise HTTPException(404, "olt not found")
    if body.kind == "snmp_community" and olt.snmp_version == "v3":
        raise HTTPException(422, "snmp_v3_unsupported")   # the Edge speaks v2c only: a community for a v3 OLT would be silently useless
    edge = conn.execute(text("SELECT seal_key_id, seal_key_state FROM edges WHERE id = :e FOR SHARE"), {"e": olt.edge_id}).first()
    if edge is None or edge.seal_key_id is None or edge.seal_key_state != "confirmed":
        raise HTTPException(409, "seal_key_not_confirmed")
    if body.key_id != edge.seal_key_id:
        raise HTTPException(409, "key_id_mismatch")
    now = conn.execute(text("SELECT now()")).scalar()
    exp = datetime.fromtimestamp(body.expires_at, UTC)
    if not (now < exp <= now + timedelta(seconds=olt_secrets.MAX_WINDOW_SECONDS)):
        raise HTTPException(422, "expires_at_out_of_window")
    pending = conn.execute(text("SELECT count(*) FROM olt_secret_deliveries WHERE olt_id = :o AND status IN ('PENDING', 'DISPATCHED') AND expires_at > now()"), {"o": olt_id}).scalar()
    if pending >= olt_secrets.MAX_PENDING_PER_OLT:
        raise HTTPException(429, "too_many_pending", headers={"Retry-After": "60"})
    new_id = conn.execute(text("INSERT INTO olt_secret_deliveries (tenant_id, id, edge_id, olt_id, olt_name, kind, key_id, expires_at, sealed, created_by) "
                               "VALUES (:t, :i, :e, :o, :n, :k, :ki, :x, :s, :by) ON CONFLICT DO NOTHING RETURNING id"),
                          {"t": p.tenant_id, "i": body.delivery_id, "e": olt.edge_id, "o": olt_id, "n": olt.name, "k": body.kind, "ki": body.key_id, "x": exp,
                           "s": olt_secrets.parse_blob(body.sealed), "by": p.id}).scalar_one_or_none()
    if new_id is None:
        raise HTTPException(409, "delivery_id_taken")
    audit(conn, p, "fleet.secret_delivery.created", "olt", str(olt_id), {"delivery_id": str(new_id), "kind": body.kind, "key_id": body.key_id})   # no blob, no content
    return {"id": str(new_id), "status": "PENDING", "kind": body.kind, "expires_at": body.expires_at}


@router.get("/v1/fleet/olts/{olt_id}/secret-deliveries")
def list_deliveries(olt_id: UUID, p: Principal = Depends(_person), conn: Connection = TENANT_CONN) -> dict:
    """The last ten deliveries of the OLT: state and code only. It does not clean up anything (the sweeper does) and it never reads the blob column (the application role cannot)."""
    if conn.execute(text("SELECT 1 FROM olts WHERE id = :i"), {"i": olt_id}).first() is None:
        raise HTTPException(404, "olt not found")
    rows = conn.execute(text("SELECT id, kind, status, code, key_id, expires_at, created_at, updated_at, attempts FROM olt_secret_deliveries WHERE olt_id = :o ORDER BY created_at DESC, id LIMIT :n"),
                        {"o": olt_id, "n": HISTORY}).all()
    return {"items": [_delivery_row(r) for r in rows]}
