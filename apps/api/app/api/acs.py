"""Cadastro de ACS por organização (ADR-0046 D2, migração 0052): a nuvem guarda só o CADASTRO do ACS; a URL e o segredo do NBI ficam no `config.json` do Edge.

Rotas de pessoa (`acs:read` / `acs:manage`, todas atrás da flag `acs_registry`): listar, ver, cadastrar, renomear/ativar/desativar. `kind` e `edge_id` são imutáveis (campo desconhecido = 422).
No máximo UM ACS ativo por Edge (409 `edge_already_has_active_acs`). Um Edge de outra organização é 404.

Rota do Edge: `POST /v1/edge/acs-status` (`jobs:execute`, limite de ingestão por agente). O Edge diz se o SEU ACS respondeu na última leitura; o estado só é gravado pela função estreita
`app_acs_edge_report` (migração 0052). Id desconhecido, de outro Edge, de outra organização, de outro `kind` ou com a flag desligada: o MESMO 404, sem criar nada e sem revelar qual foi o motivo.

Nada aqui devolve ou registra segredo, URL ou host; a auditoria leva nomes de campos, nunca valores de `settings`.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, edge_ingest_limit, require
from app.api.routes import audit
from app.core import acs, features

router = APIRouter()
LIST_LIMIT = 200
STALE_AFTER = timedelta(minutes=20)   # the Edge reports every collection round (5 min by default): a few missed rounds make the state "stale"


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "acs_registry")


def _name(v: str) -> str:
    v = v.strip()
    if not (acs.NAME_MIN <= len(v) <= acs.NAME_MAX):
        raise ValueError(f"name must have {acs.NAME_MIN} to {acs.NAME_MAX} characters")
    return v


class AcsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: str
    edge_id: UUID
    label: str | None = Field(None, min_length=1, max_length=acs.LABEL_MAX)
    enabled: bool = Field(True, strict=True)
    settings: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        return _name(v)

    @field_validator("kind")
    @classmethod
    def _k(cls, v: str) -> str:
        if v not in acs.ACS_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(acs.ACS_KINDS)}")   # never echoes the value
        return v


class AcsPatch(BaseModel):
    """What a person may change. `kind` and `edge_id` are not here on purpose: with `extra=forbid` sending them is a 422 (they are immutable; to move an ACS to another Edge, register a new one)."""
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    label: str | None = Field(None, min_length=1, max_length=acs.LABEL_MAX)
    enabled: bool | None = Field(None, strict=True)
    settings: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _n(cls, v: str | None) -> str | None:
        return None if v is None else _name(v)

    @model_validator(mode="after")
    def _not_cleared(self):
        for f in ("name", "enabled", "settings"):
            if f in self.model_fields_set and getattr(self, f) is None:
                raise ValueError(f"{f} cannot be cleared")
        return self


_SQL = ("SELECT a.id, a.name, a.kind, a.label, a.enabled, a.settings, a.created_at, a.updated_at, a.edge_id, e.name AS edge_name, "
        "a.last_seen_at, a.last_ok_at, a.device_count, a.last_error_code, now() AS now_at "
        "FROM acs_connections a JOIN edges e ON e.tenant_id = a.tenant_id AND e.id = a.edge_id ")


def _health(r) -> str:
    """unknown (the Edge never reported), error (last report failed), stale (no report for a while), ok."""
    if r.last_seen_at is None:
        return "unknown"
    if r.now_at - r.last_seen_at > STALE_AFTER:
        return "stale"
    return "error" if r.last_error_code is not None else "ok"


def _view(r) -> dict:
    return {"id": str(r.id), "name": r.name, "kind": r.kind, "label": r.label, "enabled": r.enabled, "settings": r.settings,
            "edge": {"id": str(r.edge_id), "name": r.edge_name},
            "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None, "last_ok_at": r.last_ok_at.isoformat() if r.last_ok_at else None,
            "device_count": r.device_count, "last_error_code": r.last_error_code, "health": _health(r)}


def _settings(kind: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    try:
        return acs.validate_settings(kind, raw)
    except acs.SettingsError as exc:
        raise HTTPException(422, exc.code) from None   # a stable code; neither the key nor the value is repeated


def _lock_edge(conn: Connection, edge_id: UUID) -> None:
    """Creations and (de)activations of the ACS of one Edge go one at a time; the partial unique index is the net underneath."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('acs_edge|' || CAST(:e AS text), 0))"), {"e": edge_id})


def _another_active(conn: Connection, edge_id: UUID, except_id: UUID | None) -> bool:
    return conn.execute(text("SELECT 1 FROM acs_connections WHERE edge_id = :e AND enabled AND (CAST(:x AS uuid) IS NULL OR id <> :x)"), {"e": edge_id, "x": except_id}).first() is not None


@router.get("/v1/acs")
def list_acs(p: Principal = Depends(require("acs:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    rows = conn.execute(text(_SQL + "ORDER BY lower(e.name), lower(a.name) LIMIT :n"), {"n": LIST_LIMIT}).all()
    return {"items": [_view(r) for r in rows], "truncated": len(rows) >= LIST_LIMIT, "kinds": list(acs.ACS_KINDS)}


@router.get("/v1/acs/{acs_id}")
def get_acs(acs_id: UUID, p: Principal = Depends(require("acs:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(text(_SQL + "WHERE a.id = :i"), {"i": acs_id}).first()
    if r is None:
        raise HTTPException(404, "acs not found")
    return _view(r)


@router.post("/v1/acs", status_code=201)
def create_acs(body: AcsIn, p: Principal = Depends(require("acs:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    settings = _settings(body.kind, body.settings)
    if conn.execute(text("SELECT 1 FROM edges WHERE id = :i"), {"i": body.edge_id}).first() is None:   # RLS: another organization's Edge is simply not found
        raise HTTPException(404, "edge not found")
    _lock_edge(conn, body.edge_id)
    if body.enabled and _another_active(conn, body.edge_id, None):
        raise HTTPException(409, "edge_already_has_active_acs")
    new_id = conn.execute(
        text("INSERT INTO acs_connections (tenant_id, name, kind, edge_id, label, enabled, settings, created_by) "
             "VALUES (:t, :n, :k, :e, :l, :en, CAST(:s AS jsonb), :by) "
             "ON CONFLICT (tenant_id, edge_id, lower(name)) DO NOTHING RETURNING id"),
        {"t": p.tenant_id, "n": body.name, "k": body.kind, "e": body.edge_id, "l": body.label, "en": body.enabled, "s": _json(settings), "by": p.id}).scalar_one_or_none()
    if new_id is None:
        raise HTTPException(409, "acs_name_taken")
    audit(conn, p, "acs.created", "acs", str(new_id), {"name": body.name, "kind": body.kind, "edge_id": str(body.edge_id), "enabled": body.enabled, "settings_keys": sorted(settings)})
    return _view(conn.execute(text(_SQL + "WHERE a.id = :i"), {"i": new_id}).one())


def _json(v: dict[str, Any]) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


@router.patch("/v1/acs/{acs_id}")
def update_acs(acs_id: UUID, body: AcsPatch, p: Principal = Depends(require("acs:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "nothing to change")
    pre = conn.execute(text("SELECT edge_id FROM acs_connections WHERE id = :i"), {"i": acs_id}).first()
    if pre is None:
        raise HTTPException(404, "acs not found")
    _lock_edge(conn, pre.edge_id)
    cur = conn.execute(text("SELECT id, name, kind, label, enabled, settings, edge_id FROM acs_connections WHERE id = :i FOR UPDATE"), {"i": acs_id}).first()
    if cur is None:
        raise HTTPException(404, "acs not found")
    new = {"name": body.name if "name" in sent else cur.name, "label": body.label if "label" in sent else cur.label,
           "enabled": body.enabled if "enabled" in sent else cur.enabled,
           "settings": _settings(cur.kind, body.settings) if "settings" in sent else cur.settings}
    if new["enabled"] and not cur.enabled and _another_active(conn, cur.edge_id, acs_id):
        raise HTTPException(409, "edge_already_has_active_acs")
    r = conn.execute(
        text("UPDATE acs_connections SET name = :n, label = :l, enabled = :en, settings = CAST(:s AS jsonb), updated_at = now() "
             "WHERE id = :i AND NOT EXISTS (SELECT 1 FROM acs_connections x WHERE x.edge_id = :e AND x.id <> :i AND lower(x.name) = lower(:n)) RETURNING id"),
        {"n": new["name"], "l": new["label"], "en": new["enabled"], "s": _json(new["settings"]), "i": acs_id, "e": cur.edge_id}).first()
    if r is None:
        raise HTTPException(409, "acs_name_taken")
    audit(conn, p, "acs.updated", "acs", str(acs_id), {"fields": sorted(sent), "enabled": new["enabled"]})   # field names only: never a value of `settings`
    return _view(conn.execute(text(_SQL + "WHERE a.id = :i"), {"i": acs_id}).one())


# ---- the Edge's own report -------------------------------------------------------------------
class StatusIn(BaseModel):
    """One report about ONE ACS (the Edge has a single NBI). Fields beyond these are 422."""
    model_config = ConfigDict(extra="forbid")
    acs_id: UUID
    kind: str = Field(min_length=1, max_length=32)
    ok: bool = Field(strict=True)
    device_count: int | None = Field(None, strict=True, ge=0, le=10_000_000)
    error_code: str | None = None

    @field_validator("error_code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is not None and v not in acs.ACS_ERROR_CODES:
            raise ValueError(f"error_code must be one of: {', '.join(acs.ACS_ERROR_CODES)}")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        if self.ok and (self.error_code is not None or self.device_count is None):
            raise ValueError("an ok report carries device_count and no error_code")
        if not self.ok and (self.error_code is None or self.device_count is not None):
            raise ValueError("a failed report carries error_code and no device_count")
        return self


@router.post("/v1/edge/acs-status", status_code=204)
def acs_status(body: StatusIn, p: Principal = Depends(require("jobs:execute")), _rl: None = Depends(edge_ingest_limit), conn: Connection = TENANT_CONN):
    """The Edge says whether ITS ACS answered in the round that just ended. Only the ACS of THIS Edge (and of this organization, by RLS) and of the registered `kind` is touched, through the
    narrow function of migration 0052. Everything else (unknown id, another Edge's or organization's, another kind, the feature off) is the SAME 404 and creates nothing. The audit line
    is written only when the state really changed (the Edge repeats the report every round) and carries no content beyond the closed code."""
    if p.edge_id is None:
        raise HTTPException(403, "token is not bound to an edge")
    miss = HTTPException(404, "acs not found")
    if not features.enabled(conn, p.tenant_id, "acs_registry"):
        raise miss
    res = conn.execute(text("SELECT app_acs_edge_report(:a, :e, :k, :ok, :n, :c)"),
                       {"a": body.acs_id, "e": p.edge_id, "k": body.kind, "ok": body.ok, "n": body.device_count, "c": body.error_code}).scalar()
    if res == "ignored":
        raise miss
    if res == "changed":
        audit(conn, p, "acs.status.changed", "acs", str(body.acs_id), {"kind": body.kind, "ok": body.ok, "error_code": body.error_code})
    return Response(status_code=204)


def active_acs_id(conn: Connection, tenant_id: UUID, edge_id: UUID) -> UUID | None:
    """The ACS to stamp on the CPEs an Edge reports: the ACTIVE one of THAT Edge, and only while the feature is on. None otherwise (never inferred from another Edge, never guessed)."""
    if not features.enabled(conn, tenant_id, "acs_registry"):
        return None
    return conn.execute(text("SELECT id FROM acs_connections WHERE tenant_id = :t AND edge_id = :e AND enabled"), {"t": tenant_id, "e": edge_id}).scalar_one_or_none()

