"""Synthetic-only planning guards. NOT a real OLT driver or security boundary."""
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Target:
    tenant_id: str
    olt_id: str
    pon: str
    serial: str
    firmware: str
    card: str

@dataclass(frozen=True)
class Certification:
    vendor: str
    firmware: str
    card: str
    write_certified: bool = False


def eligibility(target: Target, certification: Certification, *, observed_tenant: str,
                observed_fresh: bool, matching_order: bool, conflict: bool,
                approval: bool) -> tuple[bool, str]:
    if target.tenant_id != observed_tenant:
        return False, "cross_tenant"
    if not observed_fresh:
        return False, "stale_observation"
    if conflict:
        return False, "conflict"
    if not matching_order:
        return False, "association_unverified"
    if target.firmware != certification.firmware or target.card != certification.card:
        return False, "driver_version_not_certified"
    if not certification.write_certified:
        return False, "write_not_certified"
    if not approval:
        return False, "approval_missing"
    return True, "eligible_for_lab_plan_only"


def choose_profile_binding(requested_hash: str, existing_name: str | None,
                           existing_hash: str | None, referenced_by: int) -> Literal['reuse','create','conflict']:
    if existing_name is None:
        return 'create'
    if existing_hash == requested_hash:
        return 'reuse'
    # Never overwrite a profile with same name but differing content.
    return 'conflict'
