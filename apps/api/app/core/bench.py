"""Bench gate for writes (ADR-0030): the SECOND, explicit path that can open a write, and only for the closed list of bench targets.

The global gate (HOMOLOGATED_WRITES, empty) is untouched and keeps blocking every other target. A bench write opens only if ALL of these
hold, and any missing, divergent or unreadable source refuses it (fail closed):
  1. the operation is in the bench catalog below, with the exact parameters the catalog allows;
  2. the tenant flag `bench_writes` is on;
  3. the target is a bench target, not write-locked, and its registered Edge is the Edge the job was created for;
  4. the capability registry (ADR-0019) has `supported` + `observed|certified` with evidence for the exact
     vendor/model/firmware/protocol/operation;
  5. an open, single-use, prior authorization (written by the owner CLI) matches operation, target and parameters hash and is inside
     its window; it is CONSUMED atomically when the job is approved, and the signed envelope carries its id and end of window.
This module reads; it never talks to equipment."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, text

from app.core import features


TARGET_REF_RE = re.compile(r"[A-Za-z0-9._%-]{3,200}")


@dataclass(frozen=True)
class BenchOp:
    protocol: str          # the protocol the registry is keyed on
    params: frozenset      # the only parameter names the catalog allows (empty = none)


# ADR-0030 item 4: nothing outside this table can be a bench write. Adding a row is an amendment to the ADR and a new owner authorization.
BENCH_OPS: dict[str, BenchOp] = {
    "reboot_cpe": BenchOp("tr069", frozenset()),
    "set_wifi_ssid": BenchOp("tr069", frozenset({"ssid"})),   # H3: 2.4 GHz radio (instance 1) only; the Edge restores the original value
    # H4: the bench ONU on the real OLT. No parameter at all: port and ONT-ID come from the Edge's LOCAL list, never from here.
    "onu_reset": BenchOp("olt", frozenset()),
    "onu_deactivate": BenchOp("olt", frozenset()),    # a cycle: deactivate, verify, REACTIVATE, verify
}
# the ONLY values a parameter may take, per operation (ADR-0030 item 4); anything else is refused at preview, at the gate and again at the Edge
SSID_RE = re.compile(r"BANCADA-[A-Z0-9]{1,16}")


def params_valid(operation: str, params) -> bool:
    spec = BENCH_OPS.get(operation)
    if spec is None or not isinstance(params, dict) or set(params) != spec.params:
        return False
    if operation == "set_wifi_ssid":
        v = params["ssid"]
        return isinstance(v, str) and SSID_RE.fullmatch(v) is not None
    return True
from datetime import timedelta  # noqa: E402

# Edge-side readiness (ADR-0030 items 2, 3 and 5): the Edge must confirm the device against the ACS, keep the durable claim and enforce
# lease and the local bench list BEFORE a write can be enabled or dispatched. True since the Edge half shipped (agents/edge/internal/bench,
# jobs/claims.go, jobs/lease.go) with its tests; it is still only a precondition: the tenant flag, the bench target, the registry entry
# and the owner's prior authorization all remain required, and an Edge older than this build ignores bench envelopes (they are never run).
# The server, the owner CLI and the tests refuse everything bench-related while it is False.
EDGE_SUPPORT = True

ENVELOPE_TTL = timedelta(minutes=2)  # a bench envelope lives at most this long after it is issued
MIN_APPROVALS = 1  # a bench write always needs one approval from someone other than the requester


LEASE_TTL = timedelta(minutes=2)  # the Edge honours a lease for at most this long after receiving it (renewed on every poll)


def lease_targets(conn: Connection, tenant_id: UUID, edge_id: UUID) -> list[dict]:
    """The bench targets this Edge may act on RIGHT NOW (ADR-0030 item 4): [] unless the Edge-support switch and the tenant flag are on; only
    targets registered to this Edge, not write-locked, with a TR-069 binding. Each entry carries the owner epoch the envelope must repeat.
    A target that is unlocked/removed/moved simply stops appearing, and the lease the Edge holds runs out within LEASE_TTL."""
    if not EDGE_SUPPORT or not features.enabled(conn, tenant_id, "bench_writes"):
        return []
    rows = conn.execute(
        text("SELECT bt.owner_epoch, (SELECT b.external_id FROM cpe_protocol_bindings b WHERE b.cpe_id = bt.cpe_id AND b.protocol = 'tr069' "
             "ORDER BY b.observed_at DESC NULLS LAST, b.id LIMIT 1) AS ref FROM bench_targets bt "
             "WHERE bt.edge_id = :e AND NOT bt.write_locked ORDER BY bt.cpe_id"),
        {"e": edge_id}).all()
    return [{"target_ref": r.ref, "owner_epoch": r.owner_epoch} for r in rows if r.ref and TARGET_REF_RE.fullmatch(r.ref)]


def capability_lock_key(tenant_id: UUID, operation: str) -> str:
    return f"bench-capability|{tenant_id}|{operation}"


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def gate(conn: Connection, tenant_id: UUID, job, *, mode: str) -> str | None:
    """None if the bench write may proceed, else a short reason code. mode: 'submit'/'approve' check an OPEN authorization; 'consume' also
    consumes it (atomically, in the caller's transaction) and records it on the job; 'dispatch' requires the authorization already consumed
    by THIS job and still inside its window."""
    spec = BENCH_OPS.get(job.operation)
    if spec is None or job.target_type != "cpe":
        return "operation_not_homologated"
    if not EDGE_SUPPORT:
        return "edge_support_missing"
    # promotion of the registry entry (owner CLI, exclusive) and this evaluation (shared) cannot interleave: a decision taken here sees either
    # the whole promotion or none of it, and the promotion waits for this transaction (which also emits the envelope) to finish
    conn.execute(text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": capability_lock_key(tenant_id, job.operation)})
    if not features.enabled(conn, tenant_id, "bench_writes"):
        return "bench_writes_disabled"
    if not params_valid(job.operation, json.loads(job.params) if isinstance(job.params, str) else (job.params or {})):
        return "params_outside_catalog"
    bt = conn.execute(text("SELECT edge_id, owner_epoch, write_locked FROM bench_targets WHERE tenant_id = :t AND cpe_id = :c"),
        {"t": tenant_id, "c": job.target_id}).first()
    if bt is None:
        return "target_not_bench"
    if bt.write_locked:
        return "target_write_locked"
    if job.edge_id is None or bt.edge_id != job.edge_id:
        return "bench_edge_mismatch"
    if spec.protocol == "olt":
        # the registry profile is the OLT's: exactly one confirmed ONU<->CPE link, whose ONU belongs to an OLT with a known profile
        rows = conn.execute(
            text("SELECT ol.vendor, ol.model, ol.firmware FROM onu_cpe_links l JOIN onus u ON u.tenant_id = l.tenant_id AND u.id = l.onu_id "
                 "JOIN olts ol ON ol.tenant_id = u.tenant_id AND ol.id = u.olt_id "
                 "WHERE l.tenant_id = :t AND l.cpe_id = :c AND l.status = 'confirmed'"), {"t": tenant_id, "c": job.target_id}).all()
        cpe = rows[0] if len(rows) == 1 else None
    else:
        cpe = conn.execute(text("SELECT vendor, model, firmware FROM cpes WHERE tenant_id = :t AND id = :c"),
                           {"t": tenant_id, "c": job.target_id}).first()
    if cpe is None or not (cpe.vendor and cpe.model and cpe.firmware):
        return "capability_not_observed"
    certs = {r.certification: r for r in conn.execute(
        text("SELECT certification, evidence_ref, verified_at FROM device_capabilities WHERE tenant_id = :t AND lower(vendor) = lower(:v) AND lower(model) = lower(:m) "
             "AND firmware = :f AND protocol = :p AND operation = :o AND status = 'supported'"),
        {"t": tenant_id, "v": cpe.vendor.strip(), "m": cpe.model.strip(), "f": cpe.firmware.strip(), "p": spec.protocol, "o": job.operation})}
    complete = {k for k, r in certs.items() if r.evidence_ref is not None and r.verified_at is not None}
    observed = bool(complete & {"observed", "certified"})
    # First run (ADR-0030 amendment): without an `observed` entry, only an authorization the owner marked `first_run`, together with a complete
    # `identified` + `supported` entry of the exact profile, stands in for it. Once `observed` exists a first-run authorization no longer opens anything (a normal one is needed), and vice versa.
    first_run_possible = not observed and "identified" in complete
    if not observed and not first_run_possible:
        return "capability_not_observed"
    ph = params_hash(json.loads(job.params) if isinstance(job.params, str) else (job.params or {}))
    if mode == "dispatch":
        a = conn.execute(
            text("SELECT window_end, state, job_id, first_run FROM bench_authorizations WHERE tenant_id = :t AND id = (SELECT authorization_id FROM jobs WHERE id = :j AND tenant_id = :t) "
                 "AND operation = :o AND cpe_id = :c AND params_hash = :h"),
            {"t": tenant_id, "j": job.id, "o": job.operation, "c": job.target_id, "h": ph}).first()
        if a is None or a.state != "consumed" or a.job_id != job.id:
            return "authorization_missing"
        if a.first_run == observed:  # a first-run authorization only ever serves the no-`observed` state, a normal one only the other
            return "capability_not_observed" if a.first_run is False else "authorization_missing"
        return None if a.window_end > conn.execute(text("SELECT now()")).scalar_one() else "authorization_expired"
    a = conn.execute(
        text("SELECT id FROM bench_authorizations WHERE tenant_id = :t AND operation = :o AND cpe_id = :c AND params_hash = :h AND state = 'open' "
             "AND first_run = NOT :obs AND now() >= window_start AND now() < window_end ORDER BY window_end LIMIT 1 FOR UPDATE"),
        {"t": tenant_id, "o": job.operation, "c": job.target_id, "h": ph, "obs": observed}).first()
    if a is None:  # without an `observed` entry only a first_run authorization counts; its absence is a registry problem, not a missing one
        return "authorization_missing" if observed else "capability_not_observed"
    if mode == "consume":
        done = conn.execute(
            text("UPDATE bench_authorizations SET state = 'consumed', job_id = :j WHERE tenant_id = :t AND id = :a AND state = 'open' RETURNING id"),
            {"t": tenant_id, "j": job.id, "a": a.id}).first()
        if done is None:
            return "authorization_missing"
        conn.execute(text("UPDATE jobs SET authorization_id = :a, owner_epoch = :e WHERE tenant_id = :t AND id = :j"),
                     {"t": tenant_id, "a": a.id, "e": bt.owner_epoch, "j": job.id})
    return None


def lock_target(conn: Connection, cpe_id: UUID, reason: str) -> None:
    """Uncertain or failed bench write: no retry and no new write until the owner reconciles it (`bench-unlock`)."""
    conn.execute(text("UPDATE bench_targets SET write_locked = true, lock_reason = :r WHERE cpe_id = :c AND NOT write_locked"),
                 {"c": cpe_id, "r": reason[:300]})


EVIDENCE_FIELDS = ("Hash da intenção", "Identidades observadas", "Estado antes", "Estado depois", "Resultado da restauração", "Versões",
                   "Aprovador", "Horário", "Aceite do responsável")


def evidence_missing(text_: str) -> list[str]:
    """ADR-0030 item 7: the bench evidence file must carry every field as a non-empty `- **Field:** value` line, and must not carry
    anything that looks like a secret, an address or raw equipment output."""
    import re

    missing = [f for f in EVIDENCE_FIELDS if not re.search(rf"^- \*\*{re.escape(f)}:\*\*[ \t]*\S", text_, re.M)]
    if re.search(r"(?i)(senha|password|secret|token)\s*[:=]|\b\d{1,3}(\.\d{1,3}){3}\b", text_):
        missing.append("conteúdo sensível (credencial ou endereço IP)")
    return missing
