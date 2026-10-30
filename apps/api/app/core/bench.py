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
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, text

from app.core import features


@dataclass(frozen=True)
class BenchOp:
    protocol: str          # the protocol the registry is keyed on
    params: frozenset      # the only parameter names the catalog allows (empty = none)


# ADR-0030 item 4: nothing outside this table can be a bench write. Adding a row is an amendment to the ADR and a new owner authorization.
BENCH_OPS: dict[str, BenchOp] = {"reboot_cpe": BenchOp("tr069", frozenset())}
from datetime import timedelta  # noqa: E402

ENVELOPE_TTL = timedelta(minutes=2)  # a bench envelope lives at most this long after it is issued
MIN_APPROVALS = 1  # a bench write always needs one approval from someone other than the requester


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def gate(conn: Connection, tenant_id: UUID, job, *, mode: str) -> str | None:
    """None if the bench write may proceed, else a short reason code. mode: 'submit'/'approve' check an OPEN authorization; 'consume' also
    consumes it (atomically, in the caller's transaction) and records it on the job; 'dispatch' requires the authorization already consumed
    by THIS job and still inside its window."""
    spec = BENCH_OPS.get(job.operation)
    if spec is None or job.target_type != "cpe":
        return "operation_not_homologated"
    if not features.enabled(conn, tenant_id, "bench_writes"):
        return "bench_writes_disabled"
    if set(json.loads(job.params) if isinstance(job.params, str) else (job.params or {})) - spec.params:
        return "params_outside_catalog"
    bt = conn.execute(text("SELECT edge_id, owner_epoch, write_locked FROM bench_targets WHERE cpe_id = :c"), {"c": job.target_id}).first()
    if bt is None:
        return "target_not_bench"
    if bt.write_locked:
        return "target_write_locked"
    if job.edge_id is None or bt.edge_id != job.edge_id:
        return "bench_edge_mismatch"
    cpe = conn.execute(text("SELECT vendor, model, firmware FROM cpes WHERE id = :c"), {"c": job.target_id}).first()
    if cpe is None or not (cpe.vendor and cpe.model and cpe.firmware):
        return "capability_not_observed"
    cap = conn.execute(
        text("SELECT 1 FROM device_capabilities WHERE lower(vendor) = lower(:v) AND lower(model) = lower(:m) AND firmware = :f "
             "AND protocol = :p AND operation = :o AND status = 'supported' AND certification IN ('observed','certified') "
             "AND evidence_ref IS NOT NULL AND verified_at IS NOT NULL"),
        {"v": cpe.vendor.strip(), "m": cpe.model.strip(), "f": cpe.firmware.strip(), "p": spec.protocol, "o": job.operation}).first()
    if cap is None:
        return "capability_not_observed"
    ph = params_hash(json.loads(job.params) if isinstance(job.params, str) else (job.params or {}))
    if mode == "dispatch":
        a = conn.execute(
            text("SELECT window_end, state, job_id FROM bench_authorizations WHERE id = (SELECT authorization_id FROM jobs WHERE id = :j) "
                 "AND operation = :o AND cpe_id = :c AND params_hash = :h"),
            {"j": job.id, "o": job.operation, "c": job.target_id, "h": ph}).first()
        if a is None or a.state != "consumed" or a.job_id != job.id:
            return "authorization_missing"
        return None if a.window_end > conn.execute(text("SELECT now()")).scalar_one() else "authorization_expired"
    a = conn.execute(
        text("SELECT id FROM bench_authorizations WHERE operation = :o AND cpe_id = :c AND params_hash = :h AND state = 'open' "
             "AND now() >= window_start AND now() < window_end ORDER BY window_end LIMIT 1 FOR UPDATE"),
        {"o": job.operation, "c": job.target_id, "h": ph}).first()
    if a is None:
        return "authorization_missing"
    if mode == "consume":
        done = conn.execute(
            text("UPDATE bench_authorizations SET state = 'consumed', job_id = :j WHERE id = :a AND state = 'open' RETURNING id"),
            {"j": job.id, "a": a.id}).first()
        if done is None:
            return "authorization_missing"
        conn.execute(text("UPDATE jobs SET authorization_id = :a, owner_epoch = :e WHERE id = :j"),
                     {"a": a.id, "e": bt.owner_epoch, "j": job.id})
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
