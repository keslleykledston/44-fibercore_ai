"""ONT Configuration Manager, reading side (ADR-0034, FC24-01): configuration, capability discovery and the dynamic form schema of a CPE/ONT.

READ-ONLY toward the network: nothing here sends anything to a device. The Edge reports typed, canonical fields (never a TR-069/USP path, never a password); the
cloud validates them against the closed catalog (`app.core.ont_config`), keeps the newest device time and presents what was observed with its age. While the tenant
flag `ont_config` is off every call is refused with `feature_disabled`. A synthetic (`mock`) source is labelled as such in every answer."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, mfa_is_recent, require
from app.api.inventory import CpeBinding, _bound_edge, _capabilities, _check_observed
from app.api.routes import audit
from app.core import features, ont_config
from app.core import ont_config_changes as chg
from app.core.settings import Settings, get_settings

router = APIRouter()


class FieldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=48)
    instance: str = Field(max_length=16)
    value: bool | int | float | str
    captured_at: datetime

    _cap = field_validator("captured_at")(_check_observed)

    @model_validator(mode="after")
    def _typed(self) -> FieldIn:
        code = ont_config.check_field(self.name, self.instance, self.value)
        if code:
            raise ValueError(code)
        return self


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binding: CpeBinding
    data_model: str = Field(pattern="^(tr098|tr181|usp)$")
    fields: list[FieldIn] = Field(min_length=1, max_length=200)


class ConfigSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: UUID
    observed_at: datetime
    configs: list[ConfigIn] = Field(max_length=200)

    _obs = field_validator("observed_at")(_check_observed)

    @model_validator(mode="after")
    def _fields_not_after_the_snapshot(self) -> ConfigSnapshot:
        # a field cannot be newer than the snapshot that carries it (beyond a small tolerance): an Edge with a fast clock must not push a "future" watermark
        limit = self.observed_at + timedelta(seconds=60)
        if any(f.captured_at > limit for c in self.configs for f in c.fields):
            raise ValueError("captured_at is after the snapshot")
        return self


@router.post("/v1/edge/cpe-config", status_code=202)
def ingest_cpe_config(body: ConfigSnapshot, p: Principal = Depends(require("inventory:write")), conn: Connection = TENANT_CONN) -> dict:
    _bound_edge(p, body.edge_id)
    _gate(conn, p)   # a tenant with the module off collects nothing: turning it off stops the intake too
    if not body.configs:
        return {"status": "accepted", "cpes": 0, "fields": 0, "unknown": 0}
    bound = {
        (r.connector_id, r.protocol, r.external_id): (r.id, r.edge_id)
        for r in conn.execute(
            text("SELECT b.connector_id, b.protocol, b.external_id, c.id, c.edge_id FROM cpe_protocol_bindings b JOIN cpes c "
                 "ON c.tenant_id = b.tenant_id AND c.id = b.cpe_id WHERE b.tenant_id = :t AND b.external_id = ANY(:x)"),
            {"t": p.tenant_id, "x": [c.binding.external_id for c in body.configs]})
    }
    rows_by_key: dict[tuple, dict] = {}   # one observation per (CPE, field, instance) in a batch: the newest device time wins (a repeated field must not break the whole INSERT)
    unknown, cpes = 0, set()
    for c in body.configs:
        hit = bound.get((c.binding.connector_id, c.binding.protocol, c.binding.external_id))
        if hit is None or hit[1] != body.edge_id:   # unknown or another Edge's CPE: indistinguishable on purpose
            unknown += 1
            continue
        cpes.add(hit[0])
        for f in c.fields:
            key = (hit[0], f.name, f.instance)
            prev = rows_by_key.get(key)
            if prev is not None and f.captured_at == prev["ca"] and json.dumps(f.value) != prev["v"]:
                raise HTTPException(422, "conflicting_observations")   # same device time, different values: there is no honest winner, so the batch is refused
            if prev is None or f.captured_at > prev["ca"]:
                rows_by_key[key] = {"t": p.tenant_id, "c": hit[0], "n": f.name, "i": f.instance, "v": json.dumps(f.value), "ca": f.captured_at, "o": body.observed_at,
                                    "dm": c.data_model, "pr": c.binding.protocol}
    rows = list(rows_by_key.values())
    if rows:
        conn.execute(   # STRICTLY newer device time wins: a replay or an older read never overwrites a newer observation
            text("INSERT INTO cpe_config_fields (tenant_id, cpe_id, name, instance_key, value, captured_at, observed_at, data_model, protocol, source) "
                 "VALUES (:t,:c,:n,:i,CAST(:v AS jsonb),LEAST(:ca, now()),:o,:dm,:pr,'edge') ON CONFLICT (tenant_id, cpe_id, name, instance_key) DO UPDATE SET "
                 "value = EXCLUDED.value, captured_at = EXCLUDED.captured_at, observed_at = EXCLUDED.observed_at, received_at = now(), "
                 "data_model = EXCLUDED.data_model, protocol = EXCLUDED.protocol, source = 'edge' WHERE cpe_config_fields.captured_at < EXCLUDED.captured_at"),
            rows)
        # a tie with what is ALREADY stored (same key, same device time, another value) has no honest winner either: refuse, and the whole batch rolls back. Checked after the write,
        # inside the transaction, so a concurrent request that committed first is seen whatever the order.
        clash = conn.execute(
            text("SELECT 1 FROM unnest(CAST(:c AS uuid[]), CAST(:n AS text[]), CAST(:i AS text[]), CAST(:ca AS timestamptz[]), CAST(:v AS text[])) AS x(c, n, i, ca, v) "
                 "JOIN cpe_config_fields f ON f.cpe_id = x.c AND f.name = x.n AND f.instance_key = x.i "
                 "WHERE f.captured_at = LEAST(x.ca, now()) AND f.value <> CAST(x.v AS jsonb) LIMIT 1"),
            {"c": [r["c"] for r in rows], "n": [r["n"] for r in rows], "i": [r["i"] for r in rows], "ca": [r["ca"] for r in rows], "v": [r["v"] for r in rows]}).first()
        if clash is not None:
            raise HTTPException(422, "conflicting_observations")
    return {"status": "accepted", "cpes": len(cpes), "fields": len(rows), "unknown": unknown}


def _cpe_or_404(conn: Connection, cpe_id: UUID):
    c = conn.execute(text("SELECT id, vendor, model, firmware FROM cpes WHERE id = :i"), {"i": cpe_id}).first()
    if c is None:
        raise HTTPException(404, "cpe not found")
    return c


def _rows(conn: Connection, cpe_id: UUID) -> list[dict]:
    q = text("SELECT name, instance_key, value, captured_at, source, protocol, data_model FROM cpe_config_fields WHERE cpe_id = :c ORDER BY name, instance_key")
    out = [{"name": r.name, "instance_key": r.instance_key, "value": r.value, "captured_at": r.captured_at, "source": r.source, "protocol": r.protocol,
            "data_model": r.data_model} for r in conn.execute(q, {"c": cpe_id})]
    # optical power of the PON side comes from the OLT through the CONFIRMED ONU link: read-only, with the OLT's own observation time
    o = conn.execute(
        text("SELECT o.rx_dbm, o.observed_at FROM onu_cpe_links l JOIN onus o ON o.tenant_id = l.tenant_id AND o.id = l.onu_id WHERE l.cpe_id = :c AND l.status = 'confirmed' "
             "AND o.rx_dbm IS NOT NULL AND o.observed_at IS NOT NULL LIMIT 1"), {"c": cpe_id}).first()
    if o is not None and not any(r["name"] == "optical.rx_dbm" for r in out):
        out.append({"name": "optical.rx_dbm", "instance_key": "optical/1", "value": float(o.rx_dbm), "captured_at": o.observed_at, "source": "olt", "protocol": "olt", "data_model": "olt"})
    return out


def _gate(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "ont_config")


def _protocol(rows: list[dict]) -> str | None:
    ps = sorted({r["protocol"] for r in rows if r["protocol"] in ("tr069", "tr369")})
    return "+".join(ps) if ps else None


def _meta(rows: list[dict]) -> dict:
    return {"synthetic": any(r["source"] == "mock" for r in rows), "sources": sorted({r["source"] for r in rows})}


@router.get("/v1/cpes/{cpe_id}/ont-config/configuration")
def configuration(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    """What was observed, field by field, with its age. A password is never returned (only whether one is set)."""
    _gate(conn, p)
    c = _cpe_or_404(conn, cpe_id)
    rows = _rows(conn, cpe_id)
    now = datetime.now(UTC)
    audit(conn, p, "cpe.config.viewed", "cpe", str(cpe_id), {"fields": len(rows)})
    fields = [{"name": r["name"], "instance_key": r["instance_key"],
               "value": (("definida" if r["value"] else "não definida") if r["name"].endswith(".password.set") else r["value"]),
               "writable": False, "secret": r["name"].endswith(".password.set"), "source": r["source"], "quality": ont_config.quality(r["captured_at"], now),
               "unit": ont_config.FIELDS[r["name"]].unit, "captured_at": r["captured_at"].isoformat()} for r in rows]
    return {"cpe_id": str(cpe_id), "tenant_id": str(p.tenant_id), "revision": ont_config.revision(rows), "state": ont_config.overall_state(rows, now),
            "fingerprint": {"vendor": c.vendor, "model": c.model, "firmware": c.firmware}, "fields": fields,
            "observed_at": max((r["captured_at"] for r in rows), default=None) and max(r["captured_at"] for r in rows).isoformat(), **_meta(rows)}


@router.get("/v1/cpes/{cpe_id}/ont-config/capabilities")
def capabilities(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    """Capability discovery: what this device was seen to expose, on which real instances, and what the Capability Registry says about writing it."""
    _gate(conn, p)
    c = _cpe_or_404(conn, cpe_id)
    rows = _rows(conn, cpe_id)
    fp = {"vendor": c.vendor, "model": c.model, "firmware": c.firmware}
    reg = _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware)
    return {"cpe_id": str(cpe_id), "state": ont_config.overall_state(rows, datetime.now(UTC)), "writes_enabled": ont_config.WRITES_ENABLED,
            "items": ont_config.build_capabilities(rows, fp, _protocol(rows), reg), **_meta(rows)}


@router.get("/v1/cpes/{cpe_id}/ont-config/form-schema")
def form_schema(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    """The sidebar's forms, generated from what was observed (nothing else is shown). Read-only in this delivery."""
    _gate(conn, p)
    c = _cpe_or_404(conn, cpe_id)
    rows = _rows(conn, cpe_id)
    now = datetime.now(UTC)
    fp = {"vendor": c.vendor, "model": c.model, "firmware": c.firmware}
    caps = ont_config.build_capabilities(rows, fp, _protocol(rows), _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware))
    return {"schema_version": "2.4", "cpe_id": str(cpe_id), "tenant_id": str(p.tenant_id), "form_revision": ont_config.revision(rows), "fingerprint": fp,
            "help_slug": "ont/consultar-configuracao", **ont_config.build_form_schema(rows, now, caps), **_meta(rows)}


@router.get("/v1/ont-config/health")
def health(p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    """The module's state for this tenant: flag, writes, and how many CPEs have an observed configuration (no device data)."""
    on = features.enabled(conn, p.tenant_id, "ont_config")
    n = conn.execute(text("SELECT count(DISTINCT cpe_id) FROM cpe_config_fields")).scalar() if on else 0
    return {"enabled": on, "writes_enabled": ont_config.WRITES_ENABLED, "cpes_with_configuration": n, "catalog_fields": len(ont_config.FIELDS)}


# ---- FC24-03: preview of a change (ADR-0036). Nothing is sent to any device; every request ends BLOCKED while there is no certified capability, no enabled write and no executor.
class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str = Field(max_length=40)
    instance_key: str = Field(max_length=16)
    params: dict[str, bool | int | float | str] = Field(max_length=8)
    if_match: str = Field(pattern=r"^[0-9a-f]{16}$")   # the `form_revision` the user was looking at


def _need_high(p: Principal, settings: Settings, capability: str) -> None:
    """R3 (LAN/WAN) needs its own permission and a recent second factor, like every other R3 act. Checked here because the tier depends on the capability in the body."""
    if chg.high_risk(capability):
        if not p.can("ont_config:request_high"):
            raise HTTPException(403, "forbidden")
        if settings.mfa_recent_enforce and p.kind == "user" and not mfa_is_recent(p, settings):
            raise HTTPException(403, "mfa_recent_required")


def _change_out(r, cpe_id: UUID, now: datetime) -> dict:
    expired = r["expires_at"] <= now
    return {"id": str(r["id"]), "cpe_id": str(cpe_id), "capability": r["capability"], "instance_key": r["instance_key"], "diff": r["diff"], "risk": r["risk"],
            "approvals": r["approvals"], "status": "expired" if expired and r["status"] == "previewed" else r["status"], "blockers": r["blockers"],
            "submittable": False, "base_revision": r["base_revision"], "intent_hash": r["intent_hash"], "created_at": r["created_at"].isoformat(),
            "expires_at": r["expires_at"].isoformat(), "policy_version": chg.POLICY_VERSION, "executes": False}


@router.post("/v1/cpes/{cpe_id}/ont-config/changes/preview", status_code=201)
def preview_change(cpe_id: UUID, body: PreviewIn, p: Principal = Depends(require("ont_config:request")), settings: Settings = Depends(get_settings),
                   conn: Connection = TENANT_CONN) -> dict:
    """Validate and describe a change: from -> to per field, risk, who would have to approve, and every reason it cannot go yet. Records the preview for audit."""
    _gate(conn, p)
    if body.capability not in chg.WRITE_FIELDS:
        raise HTTPException(422, "unknown_capability")
    _need_high(p, settings, body.capability)
    c = _cpe_or_404(conn, cpe_id)
    code = chg.validate(body.capability, body.instance_key, body.params)
    if code:
        raise HTTPException(422, code)
    rows = _rows(conn, cpe_id)
    if not chg.observed(rows, body.capability, body.instance_key):
        raise HTTPException(422, "instance_not_observed")
    rev = ont_config.revision(rows)
    if body.if_match != rev:
        raise HTTPException(409, "stale_revision")
    diff = chg.build_diff(rows, body.capability, body.instance_key, body.params)
    if not any(d["changes"] for d in diff):
        raise HTTPException(422, "no_change")
    now = datetime.now(UTC)
    fp = {"vendor": c.vendor, "model": c.model, "firmware": c.firmware}
    caps = ont_config.build_capabilities(rows, fp, _protocol(rows), _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware))
    bl = chg.blockers(body.capability, body.instance_key, rows, caps, rev, now)
    risk = chg.CAPS[body.capability].risk
    row = conn.execute(
        text("INSERT INTO cpe_config_changes (tenant_id, cpe_id, capability, instance_key, params, diff, base_revision, intent_hash, risk, approvals, blockers, requested_by, expires_at) "
             "VALUES (:t,:c,:cap,:i,CAST(:p AS jsonb),CAST(:d AS jsonb),:r,:h,:k,CAST(:a AS jsonb),CAST(:b AS jsonb),:u,:e) "
             "RETURNING id, capability, instance_key, diff, risk, approvals, status, blockers, base_revision, intent_hash, created_at, expires_at"),
        {"t": p.tenant_id, "c": cpe_id, "cap": body.capability, "i": body.instance_key, "p": json.dumps(body.params, sort_keys=True), "d": json.dumps(diff), "r": rev,
         "h": chg.intent_hash(p.tenant_id, cpe_id, body.capability, body.instance_key, body.params, rev), "k": risk, "a": json.dumps(chg.APPROVALS[risk]),
         "b": json.dumps(bl), "u": p.id, "e": chg.expiry(now)}).mappings().one()
    audit(conn, p, "ont_config.change_previewed", "cpe", str(cpe_id), {"change_id": str(row["id"]), "capability": body.capability, "instance": body.instance_key,
                                                                       "fields": sorted(body.params), "risk": risk, "blockers": bl})
    return _change_out(row, cpe_id, now) | {"submittable": not bl}


def _own_change(conn: Connection, p: Principal, cpe_id: UUID, change_id: UUID):
    r = conn.execute(
        text("SELECT id, capability, instance_key, diff, risk, approvals, status, blockers, base_revision, intent_hash, created_at, expires_at, requested_by FROM cpe_config_changes "
             "WHERE id = :i AND cpe_id = :c"), {"i": change_id, "c": cpe_id}).mappings().first()
    if r is None:
        raise HTTPException(404, "change not found")
    return r


@router.get("/v1/cpes/{cpe_id}/ont-config/changes/{change_id}")
def get_change(cpe_id: UUID, change_id: UUID, p: Principal = Depends(require("ont_config:request")), conn: Connection = TENANT_CONN) -> dict:
    _gate(conn, p)
    r = _own_change(conn, p, cpe_id, change_id)
    return _change_out(r, cpe_id, datetime.now(UTC))


@router.post("/v1/cpes/{cpe_id}/ont-config/changes/{change_id}/submit")
def submit_change(cpe_id: UUID, change_id: UUID, p: Principal = Depends(require("ont_config:request")), settings: Settings = Depends(get_settings),
                  conn: Connection = TENANT_CONN) -> dict:
    """Ask for the change to go. Today it NEVER executes: the answer is 409 with the first reason, and the request is recorded as blocked (audited)."""
    _gate(conn, p)
    r = _own_change(conn, p, cpe_id, change_id)
    if r["requested_by"] != p.id:
        raise HTTPException(403, "forbidden")
    _need_high(p, settings, r["capability"])
    now = datetime.now(UTC)
    if r["expires_at"] <= now:
        raise HTTPException(410, "preview_expired")
    c = _cpe_or_404(conn, cpe_id)
    rows = _rows(conn, cpe_id)
    fp = {"vendor": c.vendor, "model": c.model, "firmware": c.firmware}
    caps = ont_config.build_capabilities(rows, fp, _protocol(rows), _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware))
    bl = chg.blockers(r["capability"], r["instance_key"], rows, caps, r["base_revision"], now)
    conn.execute(text("UPDATE cpe_config_changes SET status = 'blocked', blockers = CAST(:b AS jsonb), submitted_at = now() WHERE id = :i"), {"b": json.dumps(bl), "i": change_id})
    audit(conn, p, "ont_config.change_blocked", "cpe", str(cpe_id), {"change_id": str(change_id), "capability": r["capability"], "blockers": bl})
    # the 409 must carry the reason, but the audit row and the status above have to COMMIT first: raising here would roll them back
    return _blocked(bl)


def _blocked(bl: list[str]):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": bl[0] if bl else "executor_not_available", "blockers": bl, "executed": False})
