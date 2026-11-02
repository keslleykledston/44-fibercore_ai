"""Fleet Manager (ADR-0041, PR2 part A): register and edit OLTs and POPs. NOTHING here talks to an OLT.

A registered OLT is a row the provider names BEFORE the Edge first reads it: name, the Edge that will collect it, the expected vendor, a POP, a label and `credential_ref`, the NAME of the secret in
the Edge's own local store (D3: the Cloud never holds, receives or echoes a credential or an address; the name itself is write-only here: no response returns it, a reader sees only `has_credential_ref`). When the Edge's first snapshot arrives it adopts the row by name and fills in the real
vendor/model/firmware/level; the registration fields are left alone. There is no delete here: removing an OLT is a separate, deliberate step. The whole router answers 403 `feature_disabled`
while the tenant flag `fleet_manager` is off.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
