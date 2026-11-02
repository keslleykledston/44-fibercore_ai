"""Profile Studio core (ADR-0040, FC251-04/05/06): the typed model of an OLT service profile, its validation, the SEMANTIC diff against an observed
profile, the per-target binding decision and the plan hash. PURE: no clock, no database, no network, no randomness, and nothing here can write to equipment.

Rules that hold everywhere in this module:
- The profile is a CLOSED set of typed fields. There is no command, script or CLI text field, and such keys are refused at any depth (`FORBIDDEN_KEYS`).
- Unknown, stale or partial observation never counts as equal: it blocks reuse and any plan (fail closed). Equality is by field, unit and type, never by name or id.
- No profile is ever edited in place, shared or not, with or without references (`in_place_allowed` is always False). A different profile is a CLONE.
- Ids are local to one OLT; nothing is mapped from one OLT's id to another's.
- Imported text (a legacy CLI dump) is untrusted evidence: `sanitize_evidence` makes it inert text. It is never parsed as an instruction.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

PLAN_VERSION = "fibercore-plan-v1"

# status of a field in the diff (docs/addenda/v2.5 PROFILE_RECONCILIATION)
EQUAL, CHANGE, ADD, REMOVE, NOT_OBSERVABLE, UNSUPPORTED, CONFLICT = "EQUAL", "CHANGE", "ADD", "REMOVE", "NOT_OBSERVABLE", "UNSUPPORTED", "CONFLICT"
STRATEGIES = ("reuse_exact", "adopt_reference", "clone_new_revision", "plan_migration", "blocked")

# the typed field catalogue: name -> kind. Everything else is refused.
TAGGING = ("tagged", "untagged", "translation", "qinq", "unknown")
SHAPING = ("bng", "olt", "cpe", "none", "unknown")
FIELDS: dict[str, str] = {
    "dba_type": "str?", "fixed_kbps": "int>=0?", "assured_kbps": "int>=0?", "maximum_kbps": "int>=1?", "tconts": "tconts", "gems": "gems",
    "customer_vlan": "vlan?", "service_vlan": "vlan?", "tagging": "tagging", "ethernet_ports": "ports", "shaping_owner": "shaping", "multicast": "bool?",
    "description": "text",
}
FORBIDDEN_KEYS = frozenset({"raw_cli", "run_cli", "cli", "command", "commands", "shell", "script", "exec", "password", "secret", "credential", "credentials", "token", "private_key"})


@dataclass(frozen=True)
class Issue:
    field: str
    code: str


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _forbidden(obj: Any, path: str = "") -> list[Issue]:
    """A forbidden key at ANY depth (including `vendor_extensions`) is refused: a CLI-like key can never ride inside a typed profile."""
    out: list[Issue] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if str(k).lower() in FORBIDDEN_KEYS:
                out.append(Issue(here, "forbidden_key"))
            out.extend(_forbidden(v, here))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_forbidden(v, f"{path}[{i}]"))
    return out


def _check_value(name: str, kind: str, v: Any) -> list[Issue]:
    nullable = kind.endswith("?")
    base = kind.rstrip("?")
    if v is None:
        return [] if nullable else [Issue(name, "type")]
    if base == "str":
        return [] if isinstance(v, str) and len(v) <= 64 else [Issue(name, "type")]
    if base == "text":
        return [] if isinstance(v, str) and len(v) <= 256 else [Issue(name, "type")]
    if base == "bool":
        return [] if isinstance(v, bool) else [Issue(name, "type")]
    if base in ("int>=0", "int>=1"):
        lo = 0 if base == "int>=0" else 1
        return [] if _is_int(v) and lo <= v <= 10_000_000_000 else [Issue(name, "range")]
    if base == "vlan":
        return [] if _is_int(v) and 1 <= v <= 4094 else [Issue(name, "range")]
    if base == "tagging":
        return [] if v in TAGGING else [Issue(name, "enum")]
    if base == "shaping":
        return [] if v in SHAPING else [Issue(name, "enum")]
    if base == "ports":
        ok = isinstance(v, list) and len(v) <= 64 and all(_is_int(p) and 1 <= p <= 64 for p in v) and len(set(v)) == len(v)
        return [] if ok else [Issue(name, "type")]
    if base == "tconts":
        if not isinstance(v, list) or len(v) > 32:
            return [Issue(name, "type")]
        bad = [Issue(name, "type") for t in v if not (isinstance(t, dict) and set(t) == {"index", "dba_reference"} and _is_int(t["index"]) and t["index"] >= 0
                                                     and isinstance(t["dba_reference"], str) and 0 < len(t["dba_reference"]) <= 64)]
        idx = [t.get("index") for t in v if isinstance(t, dict)]
        return bad or ([Issue(name, "duplicate_index")] if len(set(idx)) != len(idx) else [])
    if base == "gems":
        if not isinstance(v, list) or len(v) > 128:
            return [Issue(name, "type")]
        ok_keys = ({"gem_index", "tcont_index"}, {"gem_index", "tcont_index", "vlan"})
        bad = [Issue(name, "type") for g in v if not (isinstance(g, dict) and set(g) in ok_keys and _is_int(g["gem_index"]) and g["gem_index"] >= 0
                                                     and _is_int(g["tcont_index"]) and g["tcont_index"] >= 0
                                                     and (g.get("vlan") is None or (_is_int(g["vlan"]) and 1 <= g["vlan"] <= 4094)))]
        idx = [g.get("gem_index") for g in v if isinstance(g, dict)]
        return bad or ([Issue(name, "duplicate_index")] if len(set(idx)) != len(idx) else [])
    return [Issue(name, "type")]


def validate_settings(settings: Mapping[str, Any], *, supported: frozenset[str]) -> list[Issue]:
    """Issues that stop a draft from being saved or planned (empty = valid for DRAFT ONLY). `supported` = the fields the driver certified for this
    vendor/firmware/card: a field outside it is `driver_capability_unsupported`, never silently dropped."""
    issues = _forbidden(settings)
    for name, v in settings.items():
        if name not in FIELDS:
            if str(name).lower() not in FORBIDDEN_KEYS:
                issues.append(Issue(str(name), "unknown_field"))
            continue
        if name not in supported:
            issues.append(Issue(name, "driver_capability_unsupported"))
        issues.extend(_check_value(name, FIELDS[name], v))
    a, m = settings.get("assured_kbps"), settings.get("maximum_kbps")
    if _is_int(a) and _is_int(m) and a > m:
        issues.append(Issue("assured_kbps", "qos_min_exceeds_max"))
    tc = {t["index"] for t in settings.get("tconts", []) if isinstance(t, dict) and _is_int(t.get("index"))}
    for g in settings.get("gems", []) if isinstance(settings.get("gems"), list) else []:
        if isinstance(g, dict) and _is_int(g.get("tcont_index")) and g["tcont_index"] not in tc:
            issues.append(Issue("gems", "gem_without_tcont"))
    return issues


def validate_extensions(ext: Mapping[str, Any], approved: Mapping[str, str]) -> list[Issue]:
    """`vendor_extensions` is empty unless a vendor- and firmware-scoped schema was APPROVED (name -> 'int'|'bool'|'str'): anything else is refused."""
    out = _forbidden(ext, "vendor_extensions")
    for k, v in ext.items():
        want = approved.get(k)
        if want is None:
            out.append(Issue(f"vendor_extensions.{k}", "extension_not_approved"))
        elif not ((want == "int" and _is_int(v)) or (want == "bool" and isinstance(v, bool)) or (want == "str" and isinstance(v, str) and len(v) <= 64)):
            out.append(Issue(f"vendor_extensions.{k}", "type"))
    return out


def normalize(settings: Mapping[str, Any]) -> dict[str, Any]:
    """The comparable form: lists in a fixed order, nothing added or inferred. Two profiles that mean the same thing normalise to the same value."""
    out: dict[str, Any] = {}
    for k, v in settings.items():
        if k == "tconts" and isinstance(v, list):
            out[k] = sorted(({"index": t["index"], "dba_reference": t["dba_reference"]} for t in v), key=lambda t: t["index"])
        elif k == "gems" and isinstance(v, list):
            out[k] = sorted(({"gem_index": g["gem_index"], "tcont_index": g["tcont_index"], "vlan": g.get("vlan")} for g in v), key=lambda g: g["gem_index"])
        elif k == "ethernet_ports" and isinstance(v, list):
            out[k] = sorted(v)
        else:
            out[k] = v
    return out


@dataclass(frozen=True)
class Observation:
    """A profile as the OLT reported it (an immutable snapshot). Ids and names are LOCAL to `olt_id`."""
    tenant_id: str
    olt_id: str
    native_key: str
    vendor: str
    model: str
    firmware: str
    pon_card: str
    freshness: str                      # 'fresh' | 'stale' | 'unknown'
    completeness: str                   # 'complete' | 'partial' | 'unknown'
    fingerprint: str
    reference_count: int | None         # None = unknown: it blocks migration
    settings: Mapping[str, Any] = field(default_factory=dict)
    unknown_fields: frozenset[str] = frozenset()


def semantic_diff(obs: Observation, desired: Mapping[str, Any], *, supported: frozenset[str], required: frozenset[str] | None = None) -> dict[str, str]:
    """Per field: EQUAL/CHANGE/ADD/REMOVE/NOT_OBSERVABLE/UNSUPPORTED/CONFLICT. A field the OLT did not report is NOT_OBSERVABLE, never EQUAL; a field the driver does
    not certify is UNSUPPORTED; an observed value that breaks the typed model (or contradicts itself) is CONFLICT.
    `required` = the fields whose equality must be PROVEN for this kind of profile (default: every field the driver certifies). A required field that NEITHER side
    carries is NOT_OBSERVABLE too: if both omit it, nothing was compared, so nothing is proven (an absent field is not an equal one)."""
    o, d = normalize(obs.settings), normalize(desired)
    req = supported if required is None else required
    inconsistent = {i.field for i in validate_settings(o, supported=frozenset(FIELDS)) if i.code not in ("driver_capability_unsupported",)}
    out: dict[str, str] = {}
    for f in sorted(set(o) | set(d) | set(obs.unknown_fields) | set(req)):
        if f in obs.unknown_fields:
            out[f] = NOT_OBSERVABLE
        elif f in d and f not in supported:
            out[f] = UNSUPPORTED
        elif f in o and f in inconsistent:
            out[f] = CONFLICT
        elif f not in o and f not in d:
            out[f] = NOT_OBSERVABLE
        elif f not in o:
            out[f] = ADD
        elif f not in d:
            out[f] = REMOVE
        else:
            out[f] = EQUAL if o[f] == d[f] else CHANGE
    return out


@dataclass(frozen=True)
class Target:
    """What the plan is made FOR: the OLT, its firmware and card as they are NOW, and the observation of the profile it would reuse (if any)."""
    tenant_id: str
    olt_id: str
    vendor: str
    model: str
    firmware: str
    pon_card: str
    driver_read_certified: bool
    observation: Observation | None
    source_fingerprint: str | None = None   # the fingerprint the draft was cloned from: a different one now means the source changed


def in_place_allowed(_obs: Observation | None = None) -> bool:
    """Deliberately always False: clone on write, even for a profile with zero references."""
    return False


def resolve_binding(requested: str, target: Target, diff: Mapping[str, str]) -> tuple[str, str]:
    """The strategy for ONE target and why. Ordered, fail closed; it never executes anything. `requested` can only be narrowed to `blocked`, never widened."""
    if requested not in STRATEGIES[:4]:
        return "blocked", "invalid_strategy"
    if requested == "clone_new_revision":
        # a clone writes nothing by itself and needs no observation to exist; it is still scoped to this target
        if not target.driver_read_certified:
            return "blocked", "read_not_certified"
        return "clone_new_revision", "draft_only_needs_approval_to_deploy"
    obs = target.observation
    if obs is None:
        return "blocked", "no_observation"
    if obs.tenant_id != target.tenant_id or obs.olt_id != target.olt_id:
        return "blocked", "cross_tenant_or_target"
    if not target.driver_read_certified:
        return "blocked", "read_not_certified"
    if obs.freshness != "fresh":
        return "blocked", "stale_or_unknown_snapshot"
    if obs.completeness != "complete":
        return "blocked", "incomplete_observation"
    if (obs.vendor, obs.model, obs.firmware, obs.pon_card) != (target.vendor, target.model, target.firmware, target.pon_card):
        return "blocked", "target_drift"
    if target.source_fingerprint is not None and target.source_fingerprint != obs.fingerprint:
        return "blocked", "source_changed"
    if any(v in (NOT_OBSERVABLE, UNSUPPORTED, CONFLICT) for v in diff.values()) or not diff:
        return "blocked", "incomplete_or_conflicting_observation"
    equivalent = set(diff.values()) == {EQUAL}
    if requested in ("reuse_exact", "adopt_reference"):
        return (requested, "no_device_change") if equivalent else ("blocked", "not_equivalent")
    if obs.reference_count is None:   # plan_migration
        return "blocked", "references_unknown"
    return "plan_migration", "separate_approval_and_canary_required"


def suggest_strategy(target: Target, diff: Mapping[str, str]) -> tuple[str, str]:
    """What to do when nobody asked: reuse an equivalent, fresh, complete profile; otherwise clone. Never migrates and never edits in place."""
    s, why = resolve_binding("reuse_exact", target, diff)
    if s == "reuse_exact":
        return s, why
    return resolve_binding("clone_new_revision", target, diff)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def plan_hash(*, tenant_id: str, intent_revision: str, target: Target, strategy: str, diff: Mapping[str, str], expires_at: str) -> str:
    """The hash an approval is bound to: tenant, intent revision, target identity, strategy, diff, the preconditions that must still hold (fingerprint, firmware,
    card, reference count) and the expiry. Any change after the preview gives another hash, so an approval of the old plan stops applying."""
    obs = target.observation
    body = {"v": PLAN_VERSION, "tenant": tenant_id, "target_tenant": target.tenant_id, "intent": intent_revision, "olt": target.olt_id, "vendor": target.vendor, "model": target.model,
            "firmware": target.firmware, "pon_card": target.pon_card, "strategy": strategy, "diff": dict(sorted(diff.items())),
            "pre": {"fingerprint": obs.fingerprint if obs else None, "native_key": obs.native_key if obs else None, "obs_tenant": obs.tenant_id if obs else None,
                    "obs_olt": obs.olt_id if obs else None,
                    "reference_count": obs.reference_count if obs else None, "freshness": obs.freshness if obs else None},
            "expires_at": expires_at}
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


@dataclass(frozen=True)
class TargetPlan:
    olt_id: str
    strategy: str
    reason: str
    diff: dict[str, str]
    changed_fields: list[str]
    reference_count: int | None
    writes: int
    plan_hash: str


def dry_run(*, tenant_id: str, intent_revision: str, desired: Mapping[str, Any], requested: str | None, targets: list[Target], supported: frozenset[str],
            expires_at: str, required: frozenset[str] | None = None) -> list[TargetPlan]:
    """One independent plan per OLT, ZERO writes. The same desired profile can reuse on OLT A and clone on OLT B; diffs, ids and hashes never cross targets.
    An invalid draft, or a target that belongs to another tenant than the plan, is `blocked` for that target (never planned, never hashed as if valid)."""
    invalid = bool(validate_settings(desired, supported=supported))
    plans = []
    for t in targets:
        if invalid:
            diff, strategy, why = {}, "blocked", "invalid_draft"
        elif t.tenant_id != tenant_id:
            diff, strategy, why = {}, "blocked", "cross_tenant_or_target"
        else:
            diff = semantic_diff(t.observation, desired, supported=supported, required=required) if t.observation else {}
            strategy, why = resolve_binding(requested, t, diff) if requested else suggest_strategy(t, diff)
        plans.append(TargetPlan(olt_id=t.olt_id, strategy=strategy, reason=why, diff=diff,
                                changed_fields=[f for f, v in diff.items() if v in (CHANGE, ADD, REMOVE)],
                                reference_count=t.observation.reference_count if t.observation else None, writes=0,
                                plan_hash=plan_hash(tenant_id=tenant_id, intent_revision=intent_revision, target=t, strategy=strategy, diff=diff, expires_at=expires_at)))
    return plans


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def sanitize_evidence(text: str, *, limit: int = 20_000) -> str:
    """Make imported text (a legacy CLI dump) inert PLAIN TEXT: ANSI escapes and control/bidi characters removed, length capped, then HTML-escaped, so it is safe even if a
    consumer inserts it into HTML. Nothing is stripped by pattern (a `<cr>` prompt marker is content, not markup). It is displayed as text and never parsed as an instruction."""
    t = _CTRL.sub("", _ANSI.sub("", text))[:limit]
    return html.escape(t, quote=True)
