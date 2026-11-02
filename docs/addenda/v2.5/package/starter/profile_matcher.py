"""Offline, synthetic-only semantic profile matcher: demonstrates fail-closed planning.

NOT an actual vendor normalizer, OLT driver, schema validator, or production access-control.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal
from starter.expert_policy import canonical_hash

Decision = Literal['reuse_exact','clone_new_revision','blocked']

@dataclass(frozen=True)
class Snapshot:
    tenant: str
    olt: str
    firmware: str
    card: str
    fresh: bool
    complete: bool
    native_name: str
    native_id: int
    settings: dict[str, Any]
    unknown_fields: frozenset[str] = frozenset()


def match(draft_settings: dict[str, Any], snapshot: Snapshot, *, tenant: str, olt: str,
          firmware: str, card: str, driver_read_certified: bool) -> tuple[Decision,str]:
    if snapshot.tenant != tenant or snapshot.olt != olt:
        return 'blocked','cross_scope'
    if snapshot.firmware != firmware or snapshot.card != card:
        return 'blocked','target_firmware_or_card_changed'
    if not driver_read_certified:
        return 'blocked','normalizer_not_certified'
    if not snapshot.fresh or not snapshot.complete or snapshot.unknown_fields:
        return 'blocked','incomplete_or_stale_data'
    # Exact canonical equality here is safe for synthetic same-schema fixtures.
    # Vendor normalization and complete dependency checks are REQUIRED in production.
    if canonical_hash(draft_settings) == canonical_hash(snapshot.settings):
        return 'reuse_exact','no_device_change'
    return 'clone_new_revision','different_content_do_not_overwrite'
