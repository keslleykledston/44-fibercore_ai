"""Profile Studio API (v2.5, ADR-0040): import an OLT's profile as an immutable snapshot, clone it into an editable draft, compare, and DRY-RUN per OLT.

NOTHING here writes to equipment, opens a job, or enables a write: it reads what was imported, stores drafts and simulations, and says what WOULD happen. The decision
logic is the pure `app.core.profile_studio`; this layer adds tenant scoping (RLS), permissions, `If-Match` on drafts, the freshness window, the driver-read certification
from the capability registry, audit, and the append-only record of every dry run. The whole router answers 403 `feature_disabled` while the tenant flag `profile_studio`
is off.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import features
from app.core import profile_studio as ps

router = APIRouter()

PROFILE_FRESH_FOR = timedelta(hours=6)    # a profile snapshot older than this is `stale` (profiles change rarely; the window is long on purpose, the rule is still fail closed)
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_TARGETS = 32
KINDS = ("dba", "line", "service", "tcont", "gem", "onu_type", "vlan", "traffic", "bundle")
STRATEGIES = Literal["reuse_exact", "adopt_reference", "clone_new_revision", "plan_migration"]
ALL_FIELDS = frozenset(ps.FIELDS)


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "profile_studio")


def _issues(issues: list[ps.Issue]) -> list[dict]:
    return [{"field": i.field, "code": i.code} for i in issues]


def _freshness(observed_at: datetime, stored: str, now: datetime) -> str:
    """Effective freshness NOW: a snapshot is `fresh` only if it was fresh when taken AND is still inside the window (the stored word alone never keeps it fresh)."""
    if stored == "unknown":
        return "unknown"
    return "fresh" if stored == "fresh" and now - observed_at <= PROFILE_FRESH_FOR else "stale"


def _fingerprint(native_type: str, native_key: str, firmware: str, pon_card: str, settings: dict, unknown: list[str]) -> str:
    import hashlib
    body = {"t": native_type, "k": native_key, "f": firmware, "c": pon_card, "s": ps.normalize(settings), "u": sorted(unknown)}
    return hashlib.sha256(ps.canonical_json(body).encode()).hexdigest()


def _snapshot_view(r, now: datetime, include_evidence: bool = False) -> dict:
    out = {
        "id": str(r.id), "olt_id": str(r.olt_id), "native_type": r.native_type, "native_key": r.native_key, "technology": r.technology, "vendor": r.vendor,
        "model": r.model, "firmware": r.firmware, "pon_card": r.pon_card, "observed_at": r.observed_at.isoformat(), "freshness": _freshness(r.observed_at, r.freshness, now),
        "completeness": r.completeness, "reference_count": r.reference_count, "fingerprint": r.fingerprint, "settings": r.settings,
        "unknown_fields": list(r.unknown_fields), "source": r.source, "created_at": r.created_at.isoformat(),
    }
    if include_evidence:
        out["evidence"] = r.evidence   # already sanitised and HTML-escaped at import; shown as TEXT only
    else:
        out["has_evidence"] = r.evidence is not None
    return out


def _draft_view(r) -> dict:
    return {
        "id": str(r.id), "name": r.name, "owner_id": str(r.owner_id), "source_snapshot_id": str(r.source_snapshot_id) if r.source_snapshot_id else None,
        "scope": {"technology": r.technology, "vendor": r.vendor, "model": r.model, "firmware": r.firmware, "pon_card": r.pon_card},
        "profile_kind": r.profile_kind, "target_olt_ids": [str(x) for x in r.target_olt_ids], "desired": r.desired, "vendor_extensions": r.vendor_extensions,
        "strategy": r.strategy, "reason": r.reason, "row_version": r.row_version, "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
    }


def _etag(version: int) -> str:
    return f'"{version}"'


def _olt(conn: Connection, olt_id: UUID):
    r = conn.execute(text("SELECT id, name, vendor, model, firmware FROM olts WHERE id = :i"), {"i": olt_id}).first()   # RLS: another tenant's OLT is simply not found
    if r is None:
        raise HTTPException(404, "olt not found")
    return r


def _read_certified(conn: Connection, tenant_id: UUID, olt) -> bool:
    """The driver READ of profiles is certified for this vendor/model/firmware: a registry row `olt_profile_read` that is supported and observed/certified. No row = no."""
    if not (olt.vendor and olt.model and olt.firmware):
        return False
    row = conn.execute(
        text("SELECT status, certification FROM device_capabilities WHERE tenant_id = :t AND lower(vendor) = lower(:v) AND lower(model) = lower(:m) AND firmware = :f "
             "AND protocol = :p AND operation = :o"),
        {"t": tenant_id, "v": olt.vendor.strip(), "m": olt.model.strip(), "f": olt.firmware.strip(), "p": ps.PROFILE_READ[1], "o": ps.PROFILE_READ[0]}).first()
    return bool(row and row.status == "supported" and row.certification in ("observed", "certified"))


# ---- import -------------------------------------------------------------------------------------------------------------------------------
class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    native_type: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    native_key: str = Field(pattern=r"^[A-Za-z0-9._/:-]{1,80}$")
    technology: Literal["gpon", "epon", "xgspon"]
    pon_card: str = Field(min_length=1, max_length=60)
    observed_at: datetime
    completeness: Literal["complete", "partial", "unknown"]
    reference_count: int | None = Field(None, ge=0, le=1_000_000)
    settings: dict[str, Any]
    unknown_fields: list[str] = Field(default_factory=list, max_length=32)
    evidence: str | None = Field(None, max_length=40_000)
    source: Literal["fixture", "manual_import"] = "manual_import"   # `edge_read` is reserved for the Edge reader (a later, supervised delivery)


@router.post("/v1/olts/{olt_id}/profiles/import", status_code=201)
def import_snapshot(olt_id: UUID, body: ImportIn, p: Principal = Depends(require("profiles:import")), conn: Connection = TENANT_CONN) -> dict:
    """Store what the OLT reported as an IMMUTABLE snapshot. Vendor, model and firmware come from the OLT row (not from the caller); the fingerprint is computed here.
    A value that does not fit the typed model is refused, never stored; what a parser could not map is named in `unknown_fields` (names only)."""
    _flag(conn, p)
    olt = _olt(conn, olt_id)
    if not (olt.vendor and olt.model and olt.firmware):
        raise HTTPException(409, "olt identity incomplete: vendor, model and firmware must be known before a profile is imported")
    if body.observed_at.tzinfo is None:
        raise HTTPException(422, "observed_at must be timezone-aware")
    now = datetime.now(UTC)
    if body.observed_at > now + MAX_FUTURE_SKEW:
        raise HTTPException(422, "observed_at is in the future")
    issues = ps.validate_settings(body.settings, supported=ALL_FIELDS)
    unknown = sorted(set(body.unknown_fields))
    if len(unknown) != len(body.unknown_fields) or set(unknown) - ALL_FIELDS or set(unknown) & set(body.settings):
        issues.append(ps.Issue("unknown_fields", "invalid"))
    if issues:
        raise HTTPException(422, {"issues": _issues(issues)})
    fp = _fingerprint(body.native_type, body.native_key, olt.firmware, body.pon_card, body.settings, unknown)
    ev = ps.sanitize_evidence(body.evidence) if body.evidence else None
    r = conn.execute(
        text("INSERT INTO olt_profile_snapshots (tenant_id, olt_id, native_type, native_key, technology, vendor, model, firmware, pon_card, observed_at, freshness, completeness, "
             "reference_count, fingerprint, settings, unknown_fields, evidence, source, created_by) "
             "VALUES (:t,:o,:nt,:nk,:tech,:v,:m,:f,:c,:oa,:fr,:co,:rc,:fp,CAST(:s AS jsonb),:u,:ev,:src,:by) "
             "RETURNING id, olt_id, native_type, native_key, technology, vendor, model, firmware, pon_card, observed_at, freshness, completeness, reference_count, fingerprint, "
             "settings, unknown_fields, evidence, source, created_at"),
        {"t": p.tenant_id, "o": olt_id, "nt": body.native_type, "nk": body.native_key, "tech": body.technology, "v": olt.vendor.strip(), "m": olt.model.strip(),
         "f": olt.firmware.strip(), "c": body.pon_card, "oa": body.observed_at, "fr": _freshness(body.observed_at, "fresh", now), "co": body.completeness,
         "rc": body.reference_count, "fp": fp, "s": json.dumps(ps.normalize(body.settings)), "u": unknown, "ev": ev, "src": body.source, "by": p.id}).one()
    audit(conn, p, "profile.snapshot.imported", "olt_profile_snapshot", str(r.id), {"olt_id": str(olt_id), "native_key": body.native_key, "source": body.source,
                                                                                 "fingerprint": fp[:16]})
    return _snapshot_view(r, now)


@router.get("/v1/olts/{olt_id}/profiles")
def list_profiles(olt_id: UUID, p: Principal = Depends(require("profiles:read")), conn: Connection = TENANT_CONN) -> dict:
    """The newest snapshot of each native profile of this OLT, with the freshness it has NOW, and whether the driver read is certified for this firmware."""
    _flag(conn, p)
    olt = _olt(conn, olt_id)
    now = datetime.now(UTC)
    rows = conn.execute(
        text("SELECT DISTINCT ON (native_type, native_key) id, olt_id, native_type, native_key, technology, vendor, model, firmware, pon_card, observed_at, freshness, completeness, "
             "reference_count, fingerprint, settings, unknown_fields, evidence, source, created_at FROM olt_profile_snapshots WHERE olt_id = :o "
             "ORDER BY native_type, native_key, observed_at DESC, id LIMIT 500"), {"o": olt_id}).all()
    return {"olt_id": str(olt_id), "olt_name": olt.name, "driver_read_certified": _read_certified(conn, p.tenant_id, olt),
            "items": [_snapshot_view(r, now) for r in rows], "fresh_window_hours": int(PROFILE_FRESH_FOR.total_seconds() // 3600)}


@router.get("/v1/profile-snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: UUID, p: Principal = Depends(require("profiles:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(text("SELECT * FROM olt_profile_snapshots WHERE id = :i"), {"i": snapshot_id}).first()
    if r is None:
        raise HTTPException(404, "snapshot not found")
    return _snapshot_view(r, datetime.now(UTC), include_evidence=True)


# ---- drafts -------------------------------------------------------------------------------------------------------------------------------
class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=300)
    source_snapshot_id: UUID | None = None
    # without a source snapshot the scope must be given; with one it is copied from the snapshot and these are refused
    technology: Literal["gpon", "epon", "xgspon"] | None = None
    vendor: str | None = Field(None, min_length=1, max_length=40)
    model: str | None = Field(None, min_length=1, max_length=40)
    firmware: str | None = Field(None, min_length=1, max_length=60)
    pon_card: str | None = Field(None, min_length=1, max_length=60)
    profile_kind: Literal["dba", "line", "service", "tcont", "gem", "onu_type", "vlan", "traffic", "bundle"] = "bundle"
    target_olt_ids: list[UUID] = Field(default_factory=list, max_length=MAX_TARGETS)
    desired: dict[str, Any] | None = None


class DraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=80)
    reason: str | None = Field(None, min_length=1, max_length=300)
    desired: dict[str, Any] | None = None
    vendor_extensions: dict[str, Any] | None = None
    target_olt_ids: list[UUID] | None = Field(None, max_length=MAX_TARGETS)
    strategy: STRATEGIES | None = None


def _check_targets(conn: Connection, ids: list[UUID]) -> None:
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "target_olt_ids has duplicates")
    for i in ids:
        _olt(conn, i)   # 404 for an OLT of another tenant or that does not exist


@router.post("/v1/profile-drafts", status_code=201)
def create_draft(body: DraftIn, response: Response, p: Principal = Depends(require("profiles:edit")), conn: Connection = TENANT_CONN) -> dict:
    """Clone a snapshot into a draft (or start one with an explicit scope). The draft is a COPY: the snapshot is never touched and nothing reaches the OLT."""
    _flag(conn, p)
    scope: dict[str, str]
    if body.source_snapshot_id:
        if any([body.technology, body.vendor, body.model, body.firmware, body.pon_card]):
            raise HTTPException(422, "the scope is copied from the source snapshot; do not send it")
        s = conn.execute(text("SELECT id, technology, vendor, model, firmware, pon_card, settings FROM olt_profile_snapshots WHERE id = :i"), {"i": body.source_snapshot_id}).first()
        if s is None:
            raise HTTPException(404, "snapshot not found")
        scope = {"technology": s.technology, "vendor": s.vendor, "model": s.model, "firmware": s.firmware, "pon_card": s.pon_card}
        desired = body.desired if body.desired is not None else dict(s.settings)
    else:
        if not all([body.technology, body.vendor, body.model, body.firmware, body.pon_card]):
            raise HTTPException(422, "without a source snapshot, technology, vendor, model, firmware and pon_card are required")
        scope = {"technology": body.technology, "vendor": body.vendor, "model": body.model, "firmware": body.firmware, "pon_card": body.pon_card}   # type: ignore[dict-item]
        desired = body.desired or {}
    issues = ps.validate_settings(desired, supported=ALL_FIELDS)   # a DRAFT may hold any typed field; the driver's support is checked at compare/dry-run
    if issues:
        raise HTTPException(422, {"issues": _issues(issues)})
    _check_targets(conn, body.target_olt_ids)
    r = conn.execute(
        text("INSERT INTO profile_drafts (tenant_id, name, owner_id, source_snapshot_id, technology, vendor, model, firmware, pon_card, profile_kind, target_olt_ids, desired, reason) "
             "VALUES (:t,:n,:u,:s,:tech,:v,:m,:f,:c,:k,:ids,CAST(:d AS jsonb),:r) RETURNING *"),
        {"t": p.tenant_id, "n": body.name, "u": p.id, "s": body.source_snapshot_id, "tech": scope["technology"], "v": scope["vendor"], "m": scope["model"], "f": scope["firmware"],
         "c": scope["pon_card"], "k": body.profile_kind, "ids": list(body.target_olt_ids), "d": json.dumps(ps.normalize(desired)), "r": body.reason}).one()
    audit(conn, p, "profile.draft.created", "profile_draft", str(r.id), {"source_snapshot_id": str(body.source_snapshot_id) if body.source_snapshot_id else None})
    response.headers["ETag"] = _etag(r.row_version)
    return _draft_view(r)


@router.get("/v1/profile-drafts")
def list_drafts(p: Principal = Depends(require("profiles:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    rows = conn.execute(text("SELECT * FROM profile_drafts ORDER BY updated_at DESC, id LIMIT 200")).all()
    return {"items": [_draft_view(r) for r in rows]}


def _draft(conn: Connection, draft_id: UUID, lock: bool = False):
    r = conn.execute(text("SELECT * FROM profile_drafts WHERE id = :i FOR UPDATE" if lock else "SELECT * FROM profile_drafts WHERE id = :i"), {"i": draft_id}).first()
    if r is None:
        raise HTTPException(404, "draft not found")
    return r


@router.get("/v1/profile-drafts/{draft_id}")
def get_draft(draft_id: UUID, response: Response, p: Principal = Depends(require("profiles:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = _draft(conn, draft_id)
    response.headers["ETag"] = _etag(r.row_version)
    return _draft_view(r)


def _parse_if_match(value: str | None) -> int:
    if value is None:
        raise HTTPException(428, "If-Match is required")
    try:
        return int(value.strip().removeprefix("W/").strip('"'))
    except ValueError:
        raise HTTPException(400, "If-Match must be the ETag of the draft") from None


@router.patch("/v1/profile-drafts/{draft_id}")
def patch_draft(draft_id: UUID, body: DraftPatch, response: Response, if_match: str | None = Header(default=None), p: Principal = Depends(require("profiles:edit")),
                conn: Connection = TENANT_CONN) -> dict:
    """Edit a draft with `If-Match` (the row version): a stale editor gets 412, never a silent overwrite. `vendor_extensions` stay empty until a vendor- and firmware-scoped
    schema is approved (none is yet): any key is refused. The scope and the source snapshot cannot change (that is a new draft)."""
    _flag(conn, p)
    want = _parse_if_match(if_match)
    cur = _draft(conn, draft_id, lock=True)
    if cur.row_version != want:
        raise HTTPException(412, "the draft changed since you read it; reload it")
    sets: dict[str, Any] = {}
    if body.desired is not None:
        issues = ps.validate_settings(body.desired, supported=ALL_FIELDS)
        if issues:
            raise HTTPException(422, {"issues": _issues(issues)})
        sets["desired"] = json.dumps(ps.normalize(body.desired))
    if body.vendor_extensions is not None:
        issues = ps.validate_extensions(body.vendor_extensions, {})
        if issues:
            raise HTTPException(422, {"issues": _issues(issues)})
        sets["vendor_extensions"] = json.dumps(body.vendor_extensions)
    if body.target_olt_ids is not None:
        _check_targets(conn, body.target_olt_ids)
    if not (sets or any(v is not None for v in (body.name, body.reason, body.target_olt_ids, body.strategy))):
        raise HTTPException(422, "nothing to change")
    r = conn.execute(
        text("UPDATE profile_drafts SET name = COALESCE(:n, name), reason = COALESCE(:r, reason), desired = COALESCE(CAST(:d AS jsonb), desired), "
             "vendor_extensions = COALESCE(CAST(:x AS jsonb), vendor_extensions), target_olt_ids = COALESCE(CAST(:ids AS uuid[]), target_olt_ids), "
             "strategy = COALESCE(:s, strategy), row_version = row_version + 1, updated_at = now() WHERE id = :i AND row_version = :v RETURNING *"),
        {"n": body.name, "r": body.reason, "d": sets.get("desired"), "x": sets.get("vendor_extensions"),
         "ids": list(body.target_olt_ids) if body.target_olt_ids is not None else None, "s": body.strategy, "i": draft_id, "v": want}).first()
    if r is None:
        raise HTTPException(412, "the draft changed since you read it; reload it")
    audit(conn, p, "profile.draft.edited", "profile_draft", str(draft_id), {"row_version": r.row_version, "fields": sorted(k for k, v in body.model_dump().items() if v is not None)})
    response.headers["ETag"] = _etag(r.row_version)
    return _draft_view(r)


# ---- compare and dry run ------------------------------------------------------------------------------------------------------------------
def _observation(conn: Connection, r, now: datetime) -> ps.Observation:
    return ps.Observation(
        tenant_id=str(r.tenant_id), olt_id=str(r.olt_id), native_key=r.native_key, vendor=r.vendor, model=r.model, firmware=r.firmware, pon_card=r.pon_card,
        freshness=_freshness(r.observed_at, r.freshness, now), completeness=r.completeness, fingerprint=r.fingerprint, reference_count=r.reference_count,
        settings=r.settings, unknown_fields=frozenset(r.unknown_fields))


class CompareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: UUID


@router.post("/v1/profile-drafts/{draft_id}/compare")
def compare(draft_id: UUID, body: CompareIn, p: Principal = Depends(require("profiles:read")), conn: Connection = TENANT_CONN) -> dict:
    """The SEMANTIC diff of the draft against one snapshot (read only, nothing stored). A field the OLT did not report is `NOT_OBSERVABLE`; one the driver does not certify is
    `UNSUPPORTED`; the answer says whether they are equivalent and what blocks saying so."""
    _flag(conn, p)
    d = _draft(conn, draft_id)
    s = conn.execute(text("SELECT * FROM olt_profile_snapshots WHERE id = :i"), {"i": body.snapshot_id}).first()
    if s is None:
        raise HTTPException(404, "snapshot not found")
    olt = _olt(conn, s.olt_id)
    now = datetime.now(UTC)
    certified = _read_certified(conn, p.tenant_id, olt)
    supported = ALL_FIELDS if certified else frozenset()
    obs = _observation(conn, s, now)
    diff = ps.semantic_diff(obs, d.desired, supported=supported)
    counts: dict[str, int] = {}
    for v in diff.values():
        counts[v] = counts.get(v, 0) + 1
    blockers = []
    if not certified:
        blockers.append("read_not_certified")
    if obs.freshness != "fresh":
        blockers.append("stale_or_unknown_snapshot")
    if obs.completeness != "complete":
        blockers.append("incomplete_observation")
    if any(v in (ps.NOT_OBSERVABLE, ps.UNSUPPORTED, ps.CONFLICT) for v in diff.values()):
        blockers.append("incomplete_or_conflicting_observation")
    return {"draft_id": str(draft_id), "draft_row_version": d.row_version, "snapshot_id": str(s.id), "olt_id": str(s.olt_id), "driver_read_certified": certified,
            "snapshot_freshness": obs.freshness, "snapshot_completeness": obs.completeness, "diff": diff, "counts": counts,
            "equivalent": not blockers and set(diff.values()) == {ps.EQUAL}, "blockers": blockers, "issues": _issues(ps.validate_settings(d.desired, supported=supported))}


class DryRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested: STRATEGIES | None = None
    target_olt_ids: list[UUID] | None = Field(None, max_length=MAX_TARGETS)
    ttl_minutes: int = Field(15, ge=1, le=60)


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def _targets_for(conn: Connection, p: Principal, d, olt_ids: list[UUID], now: datetime) -> tuple[list[ps.Target], list[dict], dict]:
    """One Target per OLT: the OLT as it is NOW, the driver-read certification, and the best observation of a profile on THAT OLT (an equivalent one if any, else the source's
    own profile on the source OLT). Returns the targets, the ones out of the draft's scope (blocked, not compared) and the inputs to store."""
    src = conn.execute(text("SELECT * FROM olt_profile_snapshots WHERE id = :i"), {"i": d.source_snapshot_id}).first() if d.source_snapshot_id else None
    targets: list[ps.Target] = []
    out_of_scope: list[dict] = []
    stored: dict[str, Any] = {}
    for oid in olt_ids:
        olt = _olt(conn, oid)
        certified = _read_certified(conn, p.tenant_id, olt)
        if not (_same(olt.vendor, d.vendor) and _same(olt.model, d.model) and (olt.firmware or "").strip() == d.firmware):
            out_of_scope.append({"olt_id": str(oid), "vendor": olt.vendor or "", "model": olt.model or "", "firmware": olt.firmware or ""})
            continue
        cands = conn.execute(
            text("SELECT DISTINCT ON (native_type, native_key) * FROM olt_profile_snapshots WHERE olt_id = :o AND technology = :tech "
                 "AND (CAST(:nt AS text) IS NULL OR native_type = :nt) ORDER BY native_type, native_key, observed_at DESC, id LIMIT 200"),
            {"o": oid, "tech": d.technology, "nt": src.native_type if src else None}).all()
        supported = ALL_FIELDS if certified else frozenset()
        best, nearest = None, (None, 10_000)
        for c in cands:
            ob = _observation(conn, c, now)
            diff = ps.semantic_diff(ob, d.desired, supported=supported)
            if set(diff.values()) == {ps.EQUAL} and ob.freshness == "fresh" and ob.completeness == "complete":
                best = c
                break
            distance = sum(1 for v in diff.values() if v != ps.EQUAL)
            if distance < nearest[1]:
                nearest = (c, distance)
        if best is None and src is not None and src.olt_id == oid:
            best = next((c for c in cands if c.native_key == src.native_key and c.native_type == src.native_type), None)
        if best is None:
            best = nearest[0]   # no equivalent: the CLOSEST profile on this OLT is shown as the reference for the diff and the impact (a clone is still a clone)
        obs = _observation(conn, best, now) if best is not None else None
        sfp = src.fingerprint if (src is not None and best is not None and best.native_key == src.native_key and best.olt_id == src.olt_id) else None
        t = ps.Target(tenant_id=str(p.tenant_id), olt_id=str(oid), vendor=olt.vendor.strip(), model=olt.model.strip(), firmware=olt.firmware.strip(), pon_card=d.pon_card,
                      driver_read_certified=certified, observation=obs, source_fingerprint=sfp)
        targets.append(t)
        stored[str(oid)] = {"target": dataclasses.asdict(dataclasses.replace(t, observation=None)),
                            "observation": ({**dataclasses.asdict(obs), "unknown_fields": sorted(obs.unknown_fields), "settings": dict(obs.settings)} if obs else None)}
    return targets, out_of_scope, stored


def _plan_dict(pl: ps.TargetPlan) -> dict:
    return {"olt_id": pl.olt_id, "strategy": pl.strategy, "reason": pl.reason, "diff": pl.diff, "changed_fields": pl.changed_fields, "reference_count": pl.reference_count,
            "writes": pl.writes, "plan_hash": pl.plan_hash}


@router.post("/v1/profile-drafts/{draft_id}/dry-run", status_code=201)
def dry_run(draft_id: UUID, body: DryRunIn, p: Principal = Depends(require("profiles:edit")), conn: Connection = TENANT_CONN) -> dict:
    """Simulate, per OLT, what applying the draft WOULD do: reuse, adopt, clone or blocked, with the semantic diff and the impact. ZERO writes: the run is stored (append-only)
    with its inputs so it can be replayed, and each plan carries the hash an approval would be bound to. Execution does not exist in this delivery."""
    _flag(conn, p)
    d = _draft(conn, draft_id)
    ids = body.target_olt_ids if body.target_olt_ids is not None else list(d.target_olt_ids)
    if not ids:
        raise HTTPException(422, "no target OLT: set target_olt_ids on the draft or in the request")
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "target_olt_ids has duplicates")
    now = datetime.now(UTC)
    expires = (now + timedelta(minutes=body.ttl_minutes)).replace(microsecond=0)
    targets, out_of_scope, stored = _targets_for(conn, p, d, ids, now)
    intent = f"{d.id}:{d.row_version}"
    supported_by_olt = {t.olt_id: (ALL_FIELDS if t.driver_read_certified else frozenset()) for t in targets}
    plans: list[ps.TargetPlan] = []
    for t in targets:   # one core call per target: each one validates the draft against ITS OWN driver support
        plans.extend(ps.dry_run(tenant_id=str(p.tenant_id), intent_revision=intent, desired=d.desired, requested=body.requested, targets=[t],
                                supported=supported_by_olt[t.olt_id], expires_at=expires.isoformat()))
    api_plans = [_plan_dict(x) for x in plans]
    for o in out_of_scope:   # not the vendor/model/firmware the draft is for: blocked and never compared
        t = ps.Target(tenant_id=str(p.tenant_id), olt_id=o["olt_id"], vendor=o["vendor"], model=o["model"], firmware=o["firmware"], pon_card=d.pon_card,
                      driver_read_certified=False, observation=None)
        h = ps.plan_hash(tenant_id=str(p.tenant_id), intent_revision=intent, target=t, strategy="blocked", diff={}, expires_at=expires.isoformat())
        api_plans.append({"olt_id": o["olt_id"], "strategy": "blocked", "reason": "target_out_of_scope", "diff": {}, "changed_fields": [], "reference_count": None, "writes": 0,
                          "plan_hash": h})
    issues = _issues(ps.validate_settings(d.desired, supported=ALL_FIELDS)) + _issues(ps.validate_extensions(d.vendor_extensions, {}))
    inputs = {"tenant_id": str(p.tenant_id), "intent_revision": intent, "desired": d.desired, "requested": body.requested, "expires_at": expires.isoformat(),
              "targets": stored, "out_of_scope": out_of_scope, "pon_card": d.pon_card}
    rid = conn.execute(
        text("INSERT INTO profile_dry_runs (tenant_id, draft_id, draft_row_version, requested_by, requested, expires_at, inputs, plans, issues) "
             "VALUES (:t,:d,:v,:u,:rq,:ex,CAST(:i AS jsonb),CAST(:pl AS jsonb),CAST(:is AS jsonb)) RETURNING id"),
        {"t": p.tenant_id, "d": draft_id, "v": d.row_version, "u": p.id, "rq": body.requested, "ex": expires, "i": json.dumps(inputs), "pl": json.dumps(api_plans),
         "is": json.dumps(issues)}).scalar_one()
    audit(conn, p, "profile.dry_run", "profile_dry_run", str(rid), {"draft_id": str(draft_id), "targets": len(ids), "strategies": sorted({x["strategy"] for x in api_plans})})
    return {"run_id": str(rid), "draft_id": str(draft_id), "draft_row_version": d.row_version, "expires_at": expires.isoformat(), "writes": 0, "plans": api_plans,
            "issues": issues, "executable": False}


def _replay(run) -> list[dict]:
    """Recompute the plans from the STORED inputs with the pure core: the same inputs always give the same plans and hashes."""
    i = run.inputs
    plans: list[dict] = []
    for blob in i["targets"].values():
        o = blob["observation"]
        obs = ps.Observation(**{**o, "unknown_fields": frozenset(o["unknown_fields"])}) if o else None
        t = ps.Target(**{**blob["target"], "observation": obs})
        sup = ALL_FIELDS if t.driver_read_certified else frozenset()
        plans.extend(_plan_dict(x) for x in ps.dry_run(tenant_id=i["tenant_id"], intent_revision=i["intent_revision"], desired=i["desired"], requested=i["requested"],
                                                       targets=[t], supported=sup, expires_at=i["expires_at"]))
    for o in i["out_of_scope"]:
        t = ps.Target(tenant_id=i["tenant_id"], olt_id=o["olt_id"], vendor=o["vendor"], model=o["model"], firmware=o["firmware"], pon_card=i["pon_card"],
                      driver_read_certified=False, observation=None)
        plans.append({"olt_id": o["olt_id"], "strategy": "blocked", "reason": "target_out_of_scope", "diff": {}, "changed_fields": [], "reference_count": None, "writes": 0,
                      "plan_hash": ps.plan_hash(tenant_id=i["tenant_id"], intent_revision=i["intent_revision"], target=t, strategy="blocked", diff={}, expires_at=i["expires_at"])})
    return plans


@router.get("/v1/profile-dry-runs/{run_id}")
def get_dry_run(run_id: UUID, p: Principal = Depends(require("profiles:read")), conn: Connection = TENANT_CONN) -> dict:
    """The stored run plus `reproducible` (recomputing from the stored inputs gives the stored plans) and `expired` (the hash an approval binds to stops applying)."""
    _flag(conn, p)
    r = conn.execute(text("SELECT * FROM profile_dry_runs WHERE id = :i"), {"i": run_id}).first()
    if r is None:
        raise HTTPException(404, "dry run not found")
    key = lambda x: x["olt_id"]  # noqa: E731
    return {"run_id": str(r.id), "draft_id": str(r.draft_id), "draft_row_version": r.draft_row_version, "created_at": r.created_at.isoformat(), "expires_at": r.expires_at.isoformat(),
            "expired": r.expires_at <= datetime.now(UTC), "writes": 0, "plans": r.plans, "issues": r.issues, "executable": False,
            "reproducible": sorted(_replay(r), key=key) == sorted(r.plans, key=key)}
