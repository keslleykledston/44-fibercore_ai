"""Synthetic-only policy demonstrator; NOT production API, authorization, or OLT driver."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal
import hashlib
import json

Status = Literal['reuse_exact', 'adopt_reference', 'clone_new_revision', 'plan_migration', 'blocked']

ALLOWED_FIELDS = frozenset({
    'dba_type', 'fixed_kbps', 'assured_kbps', 'maximum_kbps',
    'tconts', 'gems', 'customer_vlan', 'service_vlan', 'tagging',
    'ethernet_ports', 'shaping_owner', 'multicast', 'description',
})
DISALLOWED_KEYS = frozenset({'raw_cli', 'command', 'commands', 'shell', 'script', 'password', 'secret'})


@dataclass(frozen=True)
class ProfileObservation:
    tenant_id: str
    olt_id: str
    firmware: str
    pon_card: str
    freshness: Literal['fresh', 'stale', 'unknown']
    fingerprint: str
    reference_count: int | None
    observed_settings: dict[str, Any]
    unknown_fields: frozenset[str] = frozenset()


def canonical_hash(settings: dict[str, Any]) -> str:
    """Stable JSON hash only; equivalence is established by the vendor normalizer."""
    canon = json.dumps(settings, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canon.encode()).hexdigest()


def validate_edit(settings: dict[str, Any], allowed_by_certified_driver: set[str]) -> tuple[bool, str]:
    """Fail closed for arbitrary fields, CLI-like keys and unsupported capabilities."""
    keys = set(settings)
    if keys & DISALLOWED_KEYS:
        return False, 'raw_or_secret_field_blocked'
    if keys - ALLOWED_FIELDS:
        return False, 'unknown_field_blocked'
    if keys - allowed_by_certified_driver:
        return False, 'driver_capability_unsupported'
    if not isinstance(settings.get('customer_vlan', 1), (type(None), int)):
        return False, 'invalid_vlan'
    vlan = settings.get('customer_vlan')
    if vlan is not None and (type(vlan) is not int or not 1 <= vlan <= 4094):
        return False, 'invalid_vlan'
    if 'assured_kbps' in keys and 'maximum_kbps' in keys:
        low, high = settings['assured_kbps'], settings['maximum_kbps']
        if low is not None and high is not None and low > high:
            return False, 'qos_min_exceeds_max'
    return True, 'valid_for_draft_only'


def semantic_diff(observation: ProfileObservation, desired: dict[str, Any]) -> dict[str, str]:
    """Observe/desired diff, with unknown fields never treated as equal."""
    diff = {}
    all_fields = set(observation.observed_settings) | set(desired) | set(observation.unknown_fields)
    for field in sorted(all_fields):
        if field in observation.unknown_fields:
            diff[field] = 'not_observable'
        elif field not in observation.observed_settings:
            diff[field] = 'add'
        elif field not in desired:
            diff[field] = 'remove'
        else:
            diff[field] = 'equal' if observation.observed_settings[field] == desired[field] else 'change'
    return diff


def resolve_strategy(*, requested: Status, observation: ProfileObservation,
                     current_tenant: str, current_olt: str, current_firmware: str,
                     current_card: str, source_fingerprint: str,
                     diff: dict[str, str], certified_read: bool) -> tuple[Status, str]:
    """Plan only; NEVER executes. No in-place editing option exists."""
    if observation.tenant_id != current_tenant or observation.olt_id != current_olt:
        return 'blocked', 'cross_tenant_or_target'
    if not certified_read:
        return 'blocked', 'read_not_certified'
    if observation.freshness != 'fresh':
        return 'blocked', 'stale_or_unknown_snapshot'
    if (observation.firmware, observation.pon_card) != (current_firmware, current_card):
        return 'blocked', 'target_drift'
    if source_fingerprint != observation.fingerprint:
        return 'blocked', 'source_changed'
    if any(x == 'not_observable' for x in diff.values()):
        return 'blocked', 'incomplete_observation'
    equivalent = bool(diff) and set(diff.values()) == {'equal'}
    if requested == 'reuse_exact':
        return ('reuse_exact', 'reuse_without_writes') if equivalent else ('blocked', 'not_equivalent')
    if requested == 'adopt_reference':
        return ('adopt_reference', 'catalog_binding_only') if equivalent else ('blocked', 'not_equivalent')
    if requested == 'clone_new_revision':
        return 'clone_new_revision', 'draft_only_requires_approval_to_deploy'
    if requested == 'plan_migration':
        if observation.reference_count is None:
            return 'blocked', 'references_unknown'
        return 'plan_migration', 'separate_approval_and_canary_required'
    return 'blocked', 'invalid_strategy'


def in_place_allowed(observation: ProfileObservation) -> bool:
    """Deliberately disabled even with zero references (clone-on-write default)."""
    return False
