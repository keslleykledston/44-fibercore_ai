"""Fleet Manager (ADR-0041, PR2 part A): register and edit OLTs and POPs. NOTHING here talks to an OLT.

A registered OLT is a row the provider names BEFORE the Edge first reads it: name, the Edge that will collect it, the expected vendor, a POP, a label and `credential_ref`, the NAME of the secret in
the Edge's own local store (D3: the Cloud never holds, receives or echoes a credential or an address; the name itself is write-only here: no response returns it, a reader sees only `has_credential_ref`). When the Edge's first snapshot arrives it adopts the row by name and fills in the real
vendor/model/firmware/level; the registration fields are left alone. There is no delete here: removing an OLT is a separate, deliberate step. The whole router answers 403 `feature_disabled`
while the tenant flag `fleet_manager` is off.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import features, fleet

router = APIRouter()
LIST_LIMIT = 500


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "fleet_manager")


class PopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    code: str | None = Field(None, pattern=fleet.POP_CODE_RE.pattern)
    note: str | None = Field(None, max_length=200)


class PopPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=2, max_length=60)
    code: str | None = Field(None, pattern=fleet.POP_CODE_RE.pattern)
    note: str | None = Field(None, max_length=200)


def _pop_view(r) -> dict:
    return {"id": str(r.id), "name": r.name, "code": r.code, "note": r.note, "created_at": r.created_at.isoformat(), "olts": getattr(r, "olts", None)}


@router.get("/v1/pops")
def list_pops(p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    rows = conn.execute(text("SELECT p.id, p.name, p.code, p.note, p.created_at, (SELECT count(*) FROM olts o WHERE o.pop_id = p.id) AS olts FROM pops p ORDER BY lower(p.name) LIMIT :n"),
                        {"n": LIST_LIMIT}).all()
    return {"items": [_pop_view(r) for r in rows]}


@router.post("/v1/pops", status_code=201)
def create_pop(body: PopIn, p: Principal = Depends(require("fleet:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(text("INSERT INTO pops (tenant_id, name, code, note, created_by) VALUES (:t,btrim(:n),:c,:o,:by) ON CONFLICT DO NOTHING RETURNING id, name, code, note, created_at"),
                     {"t": p.tenant_id, "n": body.name, "c": body.code, "o": body.note, "by": p.id}).first()
    if r is None:
        raise HTTPException(409, "pop_name_taken")
    audit(conn, p, "fleet.pop.created", "pop", str(r.id), {"name": r.name})
    return _pop_view(r)


@router.patch("/v1/pops/{pop_id}")
def update_pop(pop_id: UUID, body: PopPatch, p: Principal = Depends(require("fleet:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "nothing to change")
    cur = conn.execute(text("SELECT id, name, code, note, created_at FROM pops WHERE id = :i FOR UPDATE"), {"i": pop_id}).first()
    if cur is None:
        raise HTTPException(404, "pop not found")
    if "name" in sent and body.name is None:
        raise HTTPException(422, "name cannot be cleared")
    new = {k: (getattr(body, k) if k in sent else getattr(cur, k)) for k in ("name", "code", "note")}
    r = conn.execute(text("UPDATE pops SET name = btrim(:n), code = :c, note = :o WHERE id = :i AND NOT EXISTS (SELECT 1 FROM pops x WHERE x.id <> :i AND lower(x.name) = lower(btrim(:n))) "
                          "RETURNING id, name, code, note, created_at"), {"n": new["name"], "c": new["code"], "o": new["note"], "i": pop_id}).first()
    if r is None:
        raise HTTPException(409, "pop_name_taken")
    audit(conn, p, "fleet.pop.updated", "pop", str(pop_id), {"fields": sorted(sent)})
    return _pop_view(r)


class OltIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    edge_id: UUID
    vendor: str
    pop_id: UUID | None = None
    credential_ref: str | None = Field(None, max_length=64)
    label: str | None = Field(None, min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        why = fleet.olt_name_problem(v)
        if why:
            raise ValueError(why)
        return v

    @field_validator("vendor")
    @classmethod
    def _vendor(cls, v: str) -> str:
        if v not in fleet.VENDORS:
            raise ValueError(f"vendor must be one of: {', '.join(fleet.VENDORS)}")
        return v

    @field_validator("credential_ref")
    @classmethod
    def _ref(cls, v: str | None) -> str | None:
        why = None if v is None else fleet.credential_ref_problem(v)
        if why:
            raise ValueError(why)   # never echoes the value
        return v


class OltPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pop_id: UUID | None = None
    credential_ref: str | None = Field(None, max_length=64)
    label: str | None = Field(None, min_length=1, max_length=80)

    @field_validator("credential_ref")
    @classmethod
    def _ref(cls, v: str | None) -> str | None:
        why = None if v is None else fleet.credential_ref_problem(v)
        if why:
            raise ValueError(why)
        return v


_OLT_SQL = ("SELECT o.id, o.name, o.vendor, o.model, o.firmware, o.support_level, o.observed_at, (o.credential_secret_ref IS NOT NULL) AS has_ref, o.label, o.pop_id, p.name AS pop_name, "
            "o.registered_at, o.edge_id, e.name AS edge_name, e.last_heartbeat_at, (SELECT count(*) FROM onus n WHERE n.olt_id = o.id) AS onu_count "
            "FROM olts o JOIN edges e ON e.id = o.edge_id LEFT JOIN pops p ON p.id = o.pop_id ")


def _olt_view(r) -> dict:
    return {"id": str(r.id), "name": r.name, "vendor": r.vendor, "model": r.model, "firmware": r.firmware, "support_level": r.support_level,
            "observed_at": r.observed_at.isoformat() if r.observed_at else None, "has_credential_ref": r.has_ref,   # the NAME of the secret is never returned (least exposure): a reader sees only that one is set
            
            "label": r.label, "pop": {"id": str(r.pop_id), "name": r.pop_name} if r.pop_id else None, "registered": r.registered_at is not None,
            "registered_at": r.registered_at.isoformat() if r.registered_at else None, "edge": {"id": str(r.edge_id), "name": r.edge_name},
            "edge_last_heartbeat_at": r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None, "onu_count": r.onu_count,
            "collected": r.observed_at is not None}


@router.get("/v1/fleet/olts")
def list_olts(p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    rows = conn.execute(text(_OLT_SQL + "ORDER BY lower(o.name) LIMIT :n"), {"n": LIST_LIMIT}).all()
    return {"items": [_olt_view(r) for r in rows], "truncated": len(rows) >= LIST_LIMIT}


@router.get("/v1/fleet/olts/{olt_id}")
def get_olt(olt_id: UUID, p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(text(_OLT_SQL + "WHERE o.id = :i"), {"i": olt_id}).first()
    if r is None:
        raise HTTPException(404, "olt not found")
    return _olt_view(r)


def _check_pop(conn: Connection, pop_id: UUID | None) -> None:
    if pop_id is not None and conn.execute(text("SELECT 1 FROM pops WHERE id = :i"), {"i": pop_id}).first() is None:   # RLS: another tenant's POP is simply not found
        raise HTTPException(404, "pop not found")


@router.post("/v1/fleet/olts", status_code=201)
def register_olt(body: OltIn, p: Principal = Depends(require("fleet:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    if conn.execute(text("SELECT 1 FROM edges WHERE id = :i"), {"i": body.edge_id}).first() is None:
        raise HTTPException(404, "edge not found")
    _check_pop(conn, body.pop_id)
    new_id = conn.execute(
        text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level, credential_secret_ref, pop_id, label, registered_by, registered_at) "
             "VALUES (:t,:e,:n,:v,'identified',:c,:pop,:l,:by,:at) ON CONFLICT (tenant_id, name) DO NOTHING RETURNING id"),
        {"t": p.tenant_id, "e": body.edge_id, "n": body.name, "v": body.vendor, "c": body.credential_ref, "pop": body.pop_id, "l": body.label, "by": p.id, "at": datetime.now(UTC)}).scalar_one_or_none()
    if new_id is None:
        raise HTTPException(409, "olt_name_taken")
    audit(conn, p, "fleet.olt.registered", "olt", str(new_id), {"name": body.name, "vendor": body.vendor, "pop": str(body.pop_id) if body.pop_id else None,
                                                                "has_credential_ref": body.credential_ref is not None})   # the NAME of the secret is not logged, only that one is set
    return _olt_view(conn.execute(text(_OLT_SQL + "WHERE o.id = :i"), {"i": new_id}).one())


@router.patch("/v1/fleet/olts/{olt_id}")
def update_olt(olt_id: UUID, body: OltPatch, p: Principal = Depends(require("fleet:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "nothing to change")
    if conn.execute(text("SELECT 1 FROM olts WHERE id = :i FOR UPDATE"), {"i": olt_id}).first() is None:
        raise HTTPException(404, "olt not found")
    if "pop_id" in sent:
        _check_pop(conn, body.pop_id)
    sets, args = [], {"i": olt_id}
    for field, col in (("pop_id", "pop_id"), ("credential_ref", "credential_secret_ref"), ("label", "label")):
        if field in sent:   # an explicit null clears the field
            sets.append(f"{col} = :{field}")
            args[field] = getattr(body, field)
    conn.execute(text(f"UPDATE olts SET {', '.join(sets)} WHERE id = :i"), args)
    audit(conn, p, "fleet.olt.updated", "olt", str(olt_id), {"fields": sorted(sent)})
    return _olt_view(conn.execute(text(_OLT_SQL + "WHERE o.id = :i"), {"i": olt_id}).one())


# ---- PR2 part B: the connection test. It is NOT a channel of its own: it is the closed read `olt.connection` (the same `display version` already validated) asked through the existing
# `olt_query` job engine, so it keeps every gate, the Edge lease/queue and the cache-first rule. On top, the budget the owner approved (ADR-0041 §4.1): ONE test per OLT every 15 minutes and
# FOUR per hour, counted here (and again at the Edge). A fresh stored identity answers without touching the equipment and spends nothing.
TEST_QUERY = "olt.connection"
TEST_GAP = timedelta(minutes=15)
TEST_PER_HOUR = 4


def _norm(v: str | None) -> str:
    return "".join(ch for ch in (v or "").lower() if ch.isalnum())


def _identity(olt, data: dict) -> dict:
    """What the OLT said about itself (typed, from the read) next to what the registration/collection already knew. `vendor` is the registered one: `display version` does not name it."""
    known = olt.model is not None and olt.firmware is not None
    return {"vendor": olt.vendor, "model": data["product"], "firmware": data["version"], "patch": data["patch"], "uptime_seconds": data["uptime_seconds"],
            "matches_collected": (_norm(olt.model) == _norm(data["product"]) and _norm(olt.firmware) == _norm(data["version"])) if known else None}


def _budget(conn: Connection, olt_id: UUID) -> dict:
    now = conn.execute(text("SELECT now()")).scalar()
    ts = [r[0] for r in conn.execute(text("SELECT requested_at FROM olt_connection_tests WHERE olt_id = :o AND outcome = 'submitted' AND requested_at > now() - interval '1 hour' "
                                          "ORDER BY requested_at DESC"), {"o": olt_id}).all()]
    wait = 0.0
    if ts and now - ts[0] < TEST_GAP:
        wait = max(wait, (ts[0] + TEST_GAP - now).total_seconds())
    if len(ts) >= TEST_PER_HOUR:
        wait = max(wait, (ts[TEST_PER_HOUR - 1] + timedelta(hours=1) - now).total_seconds())
    return {"used_last_hour": len(ts), "max_per_hour": TEST_PER_HOUR, "gap_minutes": int(TEST_GAP.total_seconds() // 60), "wait_seconds": int(wait) + (1 if wait > 0 else 0)}


@router.post("/v1/fleet/olts/{olt_id}/connection-test")
def connection_test(olt_id: UUID, idempotency_key: str | None = Header(None, alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
                    p: Principal = Depends(require("fleet:test")), conn: Connection = TENANT_CONN) -> dict:
    from app.api import jobs
    from app.core import olt_cache, olt_query
    _flag(conn, p)
    if not (p.can("jobs:request") and p.can("jobs:read")):
        raise HTTPException(403, "forbidden")
    olt = conn.execute(text("SELECT id, vendor, model, firmware FROM olts WHERE id = :i"), {"i": olt_id}).first()
    if olt is None:
        raise HTTPException(404, "olt not found")
    reason = jobs._query_gate(conn, p.tenant_id, {"query_id": TEST_QUERY})   # the very gates of any olt_query: flag, rollout, Edge channel
    if reason is not None:
        raise HTTPException(409, reason)
    hit = olt_cache.latest(conn, olt_id, TEST_QUERY, "")
    if hit is not None and not hit["stale"] and hit.get("source") == "job" and olt_query.check_result(TEST_QUERY, hit["data"]):
        conn.execute(text("INSERT INTO olt_connection_tests (tenant_id, olt_id, outcome, requested_by) VALUES (:t,:o,'cached',:by)"), {"t": p.tenant_id, "o": olt_id, "by": p.id})
        return {"outcome": "cached", "identity": _identity(olt, hit["data"]), "asked_at": hit["asked_at"], "age_seconds": hit["age_seconds"]}
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"fleet-test:{olt_id}"})   # the count below and the row that spends the budget are one step
    if idempotency_key is not None and conn.execute(text("SELECT 1 FROM jobs WHERE idempotency_key = :k"), {"k": idempotency_key}).first() is not None:
        # a retry of a request already accepted: answered from the job it created BEFORE the budget (which that very request raised), and refused if the key was used for another intent
        view = jobs.create_preview(jobs.PreviewIn(operation="olt_query", target_id=olt_id, params={"query_id": TEST_QUERY}), idempotency_key, p, conn, fleet_test=True)
        return {"outcome": "existing", "job_id": view["id"], "job_status": view["status"], "budget": _budget(conn, olt_id)}
    b = _budget(conn, olt_id)
    if b["wait_seconds"] > 0:
        raise HTTPException(429, "test_budget", headers={"Retry-After": str(b["wait_seconds"])})
    view = jobs.create_preview(jobs.PreviewIn(operation="olt_query", target_id=olt_id, params={"query_id": TEST_QUERY}), idempotency_key or f"fleet-{uuid4().hex}", p, conn, fleet_test=True)
    if view["status"] != "PREVIEWED":   # the same key again: nothing new is created and nothing is spent
        return {"outcome": "existing", "job_status": view["status"], "budget": b}
    view = jobs.submit(UUID(view["id"]), p, conn)
    conn.execute(text("INSERT INTO olt_connection_tests (tenant_id, olt_id, job_id, outcome, requested_by) VALUES (:t,:o,:j,'submitted',:by)"),
                 {"t": p.tenant_id, "o": olt_id, "j": view["id"], "by": p.id})
    audit(conn, p, "fleet.olt.connection_test", "olt", str(olt_id), {"job_id": view["id"]})
    return {"outcome": "submitted", "job_status": view["status"], "budget": _budget(conn, olt_id)}


@router.get("/v1/fleet/olts/{olt_id}/connection-tests")
def connection_tests(olt_id: UUID, p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    from app.core import olt_cache, olt_query
    _flag(conn, p)
    olt = conn.execute(text("SELECT id, vendor, model, firmware FROM olts WHERE id = :i"), {"i": olt_id}).first()
    if olt is None:
        raise HTTPException(404, "olt not found")
    rows = conn.execute(text("SELECT t.id, t.outcome, t.requested_at, j.status AS job_status FROM olt_connection_tests t LEFT JOIN jobs j ON j.id = t.job_id "
                             "WHERE t.olt_id = :o ORDER BY t.requested_at DESC LIMIT 10"), {"o": olt_id}).all()
    hit = olt_cache.latest(conn, olt_id, TEST_QUERY, "")
    latest = None
    if hit is not None and hit.get("source") == "job" and olt_query.check_result(TEST_QUERY, hit["data"]):
        latest = {"identity": _identity(olt, hit["data"]), "asked_at": hit["asked_at"], "age_seconds": hit["age_seconds"], "stale": hit["stale"]}
    return {"items": [{"id": str(r.id), "outcome": r.outcome, "requested_at": r.requested_at.isoformat(), "job_status": r.job_status} for r in rows], "latest": latest, "budget": _budget(conn, olt_id)}
