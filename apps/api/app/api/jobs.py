"""Job gate: preview -> submit -> approve -> signed dispatch -> result, as a compare-and-set state machine.

Safety properties (each covered by tests):
- Only operations in OPERATIONS exist; WRITE operations are blocked until homologated per firmware/model (HOMOLOGATED_WRITES is
  empty in this build), so no write can reach APPROVED/DISPATCHED. The Edge independently refuses operations outside its local list.
- An approval covers one job (tenant, target, operation, params hash, expiry), cannot be given by the requester for R2+,
  R3 needs two distinct approvers, and expires.
- The Cloud signs a short-lived envelope (Ed25519); the Edge verifies signature, expiry, nonce and edge/tenant binding.
- SUCCEEDED requires the Edge to report a post-check; otherwise the outcome is UNKNOWN (never assumed)."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import bench, jobsign
from app.core.settings import Settings, get_settings
from app.events import outbox

router = APIRouter()

JOB_TTL = timedelta(minutes=15)
POLICY_VERSION = "2026-10-28.1"


@dataclass(frozen=True)
class Operation:
    risk: Literal["R0", "R1", "R2", "R3"]
    target: Literal["olt", "cpe"]
    writes: bool
    approvals: int


OPERATIONS: dict[str, Operation] = {
    "collect": Operation("R0", "olt", False, 0),
    "refresh": Operation("R0", "cpe", False, 0),
    "reboot_cpe": Operation("R1", "cpe", True, 0),
    "set_wifi_ssid": Operation("R2", "cpe", True, 1),
    "provision_onu": Operation("R3", "olt", True, 2),
}
# (operation) names whose firmware/model/transport homologation is complete. EMPTY by design in Sprint 3.
HOMOLOGATED_WRITES: frozenset[str] = frozenset()

# the ACS device ids the Edge accepts as a refresh target (same pattern as agents/edge/internal/jobs)
TARGET_REF_RE = re.compile(r"[A-Za-z0-9._%-]{3,200}")

TRANSITIONS: dict[str, frozenset[str]] = {
    "PREVIEWED": frozenset({"PENDING_APPROVAL", "APPROVED", "CANCELLED", "EXPIRED"}),
    "PENDING_APPROVAL": frozenset({"APPROVED", "CANCELLED", "EXPIRED"}),
    "APPROVED": frozenset({"DISPATCHED", "CANCELLED", "EXPIRED"}),
    "DISPATCHED": frozenset({"ACCEPTED", "SUCCEEDED", "FAILED", "UNKNOWN", "EXPIRED"}),
    "ACCEPTED": frozenset({"DEVICE_PENDING", "VERIFYING", "SUCCEEDED", "FAILED", "UNKNOWN"}),
    "DEVICE_PENDING": frozenset({"VERIFYING", "SUCCEEDED", "FAILED", "UNKNOWN"}),
    "VERIFYING": frozenset({"SUCCEEDED", "FAILED", "UNKNOWN"}),
}


def _blocked_reason(op_name: str) -> str | None:
    op = OPERATIONS[op_name]
    if op.writes and op_name not in HOMOLOGATED_WRITES:
        return "operation_not_homologated"
    return None


def _write_gate(conn: Connection, tenant_id: UUID, row, mode: str) -> str | None:
    """The global gate first (HOMOLOGATED_WRITES, empty); a write it blocks can still pass ONLY through the bench gate (ADR-0030)."""
    reason = _blocked_reason(row.operation)
    if reason is None or row.operation not in bench.BENCH_OPS:
        return reason
    refusal = bench.gate(conn, tenant_id, row, mode=mode)
    return "operation_not_homologated" if refusal == "bench_writes_disabled" else refusal  # flag off: the bench path is not visible


def cas(conn: Connection, job_id: UUID, to: str, *, extra: str = "", params: dict | None = None) -> bool:
    """Atomic transition guarded by the legal-source set; returns False if the job is not in a legal source state."""
    sources = [s for s, tos in TRANSITIONS.items() if to in tos]
    res = conn.execute(
        text(f"UPDATE jobs SET status = :to, updated_at = now() {extra} WHERE id = :i AND status = ANY(:src) RETURNING id"),  # noqa: S608
        {"to": to, "i": job_id, "src": sources, **(params or {})},
    ).first()
    return res is not None


class PreviewIn(BaseModel):
    operation: str = Field(min_length=1, max_length=40)
    target_id: UUID
    params: dict = Field(default_factory=dict)


def _intent_hash(op: str, target_type: str, target_id: UUID, params: dict) -> str:
    blob = json.dumps({"operation": op, "target_type": target_type, "target_id": str(target_id), "params": params},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _view(r) -> dict:
    return {"id": str(r.id), "operation": r.operation, "target_type": r.target_type, "target_id": str(r.target_id),
            "risk": r.risk, "status": r.status, "required_approvals": r.required_approvals,
            "blocked_reason": _blocked_reason(r.operation) if r.operation in OPERATIONS else "unknown_operation",
            "expires_at": r.expires_at.isoformat() if r.expires_at else None, "result": r.result,
            "created_at": r.created_at.isoformat()}


COLS = ("id, operation, target_type, target_id, risk, status, required_approvals, expires_at, result, created_at, "
        "requested_by, edge_id, idempotency_key, intent_hash, params, authorization_id, owner_epoch")


@router.post("/v1/jobs/preview", status_code=201)
def preview(
    body: PreviewIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    p: Principal = Depends(require("jobs:request")),
    conn: Connection = TENANT_CONN,
) -> dict:
    op = OPERATIONS.get(body.operation)
    if op is None:
        raise HTTPException(422, "unknown operation")
    if body.params:
        raise HTTPException(422, "this operation accepts no parameters yet")  # strict: nothing free-form reaches an Edge
    table = {"olt": "olts", "cpe": "cpes"}[op.target]
    tgt = conn.execute(text(f"SELECT edge_id FROM {table} WHERE id = :i"), {"i": body.target_id}).first()  # noqa: S608
    if tgt is None:
        raise HTTPException(404, "target not found")
    ih = _intent_hash(body.operation, op.target, body.target_id, body.params)
    existing = conn.execute(text(f"SELECT {COLS} FROM jobs WHERE idempotency_key = :k"), {"k": idempotency_key}).first()  # noqa: S608
    if existing:
        if existing.intent_hash.strip() != ih:
            raise HTTPException(409, "idempotency key reused with a different intent")
        return _view(existing)
    row = conn.execute(
        text(
            f"INSERT INTO jobs (tenant_id, edge_id, target_type, target_id, operation, params, intent_hash, idempotency_key, "  # noqa: S608
            f"risk, required_approvals, requested_by) VALUES (:t,:e,:tt,:ti,:op,CAST(:pa AS jsonb),:ih,:ik,:rk,:ra,:rb) RETURNING {COLS}"
        ),
        {"t": p.tenant_id, "e": tgt.edge_id, "tt": op.target, "ti": body.target_id, "op": body.operation, "pa": json.dumps(body.params),
         "ih": ih, "ik": idempotency_key, "rk": op.risk,
         "ra": max(op.approvals, bench.MIN_APPROVALS) if body.operation in bench.BENCH_OPS else op.approvals, "rb": p.id},
    ).one()
    audit(conn, p, "job.preview", "job", str(row.id), {"operation": body.operation, "risk": op.risk})
    return _view(row)


def _load(conn: Connection, job_id: UUID, lock: bool = True):
    row = conn.execute(text(f"SELECT {COLS}, nonce FROM jobs WHERE id = :i" + (" FOR UPDATE" if lock else "")), {"i": job_id}).first()  # noqa: S608
    if row is None:
        raise HTTPException(404, "job not found")
    return row


def _expire_if_needed(conn: Connection, row) -> None:
    if row.expires_at and row.expires_at <= datetime.now(UTC) and row.status in ("PENDING_APPROVAL", "APPROVED", "PREVIEWED"):
        cas(conn, row.id, "EXPIRED")
        raise HTTPException(409, "job expired")


@router.post("/v1/jobs/{job_id}/submit")
def submit(job_id: UUID, p: Principal = Depends(require("jobs:request")), conn: Connection = TENANT_CONN) -> dict:
    row = _load(conn, job_id)
    if row.requested_by != p.id:
        raise HTTPException(403, "only the requester can submit")
    if row.status != "PREVIEWED":
        raise HTTPException(409, f"job is {row.status}")
    reason = _write_gate(conn, p.tenant_id, row, "submit")
    if reason:
        raise HTTPException(409, reason)  # write gate: never leaves PREVIEWED
    to = "PENDING_APPROVAL" if row.required_approvals > 0 else "APPROVED"
    if not cas(conn, job_id, to, extra=", expires_at = :exp, nonce = :nonce",
               params={"exp": datetime.now(UTC) + JOB_TTL, "nonce": secrets.token_hex(16)}):
        raise HTTPException(409, "illegal transition")
    audit(conn, p, "job.submit", "job", str(job_id), {"to": to})
    return _view(_load(conn, job_id, lock=False))


@router.post("/v1/jobs/{job_id}/approve")
def approve(job_id: UUID, p: Principal = Depends(require("jobs:approve")), conn: Connection = TENANT_CONN) -> dict:
    row = _load(conn, job_id)
    _expire_if_needed(conn, row)
    if row.status != "PENDING_APPROVAL":
        raise HTTPException(409, f"job is {row.status}")
    if row.requested_by == p.id:
        raise HTTPException(403, "requester cannot approve their own job")
    reason = _write_gate(conn, p.tenant_id, row, "approve")
    if reason:
        raise HTTPException(409, reason)
    dup = conn.execute(
        text("INSERT INTO job_approvals (tenant_id, job_id, approver_id) VALUES (:t,:j,:a) ON CONFLICT DO NOTHING RETURNING id"),
        {"t": p.tenant_id, "j": job_id, "a": p.id},
    ).first()
    if dup is None:
        raise HTTPException(409, "already approved by you")
    n = conn.execute(text("SELECT count(*) FROM job_approvals WHERE job_id = :j"), {"j": job_id}).scalar_one()
    audit(conn, p, "job.approve", "job", str(job_id), {"approvals": n, "required": row.required_approvals})
    if n >= row.required_approvals:
        if _blocked_reason(row.operation):  # a bench write: the prior authorization is consumed atomically with the approval
            reason = bench.gate(conn, p.tenant_id, row, mode="consume")
            if reason:
                raise HTTPException(409, reason)  # nothing is committed: no approval row, no consumed authorization
        cas(conn, job_id, "APPROVED")
    return _view(_load(conn, job_id, lock=False))


@router.post("/v1/jobs/{job_id}/cancel")
def cancel(job_id: UUID, p: Principal = Depends(require("jobs:request")), conn: Connection = TENANT_CONN) -> dict:
    row = _load(conn, job_id)
    if row.requested_by != p.id and not p.can("jobs:approve"):
        raise HTTPException(403, "only the requester or an approver can cancel")
    if not cas(conn, job_id, "CANCELLED"):
        raise HTTPException(409, f"job is {row.status}")
    audit(conn, p, "job.cancel", "job", str(job_id))
    return _view(_load(conn, job_id, lock=False))


@router.get("/v1/jobs")
def list_jobs(
    limit: int = Query(50, ge=1, le=200), p: Principal = Depends(require("jobs:read")), conn: Connection = TENANT_CONN
) -> list[dict]:
    rows = conn.execute(text(f"SELECT {COLS} FROM jobs ORDER BY created_at DESC LIMIT :l"), {"l": limit})  # noqa: S608
    return [_view(r) for r in rows]


@router.get("/v1/jobs/{job_id}")
def get_job(job_id: UUID, p: Principal = Depends(require("jobs:read")), conn: Connection = TENANT_CONN) -> dict:
    return _view(_load(conn, job_id, lock=False))


# ---- Edge side --------------------------------------------------------------------------------
@router.get("/v1/edge/jobs/next")
def next_job(
    response: Response,
    p: Principal = Depends(require("jobs:execute")),
    conn: Connection = TENANT_CONN,
    settings: Settings = Depends(get_settings),
):
    if p.edge_id is None:
        raise HTTPException(403, "token is not bound to an edge")
    if not settings.job_signing_key:
        raise HTTPException(503, "job signing key not configured")  # fail closed: nothing is dispatched unsigned
    # Opportunistic sweep: a job dispatched but never reported (Edge died / envelope rejected) must not stay DISPATCHED forever.
    swept = conn.execute(
        text("UPDATE jobs SET status = 'EXPIRED', updated_at = now() WHERE edge_id = :e AND status = 'DISPATCHED' "
             "AND expires_at < now() - interval '5 minutes' RETURNING operation, target_id"),
        {"e": p.edge_id},
    ).all()
    for s_ in swept:  # a bench write that was sent and never reported may have been applied: lock the target (ADR-0030 item 6)
        if s_.operation in bench.BENCH_OPS and _blocked_reason(s_.operation):
            bench.lock_target(conn, s_.target_id, "bench write dispatched and never reported")
    row = conn.execute(
        text(
            f"SELECT {COLS}, nonce FROM jobs WHERE edge_id = :e AND status = 'APPROVED' "  # noqa: S608
            "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
        ),
        {"e": p.edge_id},
    ).first()
    if row is None:
        response.status_code = 204
        return None
    if row.expires_at <= datetime.now(UTC):
        cas(conn, row.id, "EXPIRED")
        response.status_code = 204
        return None
    if _write_gate(conn, p.tenant_id, row, "dispatch"):  # defence in depth: a write is never dispatched unless a gate passes NOW
        cas(conn, row.id, "CANCELLED")
        response.status_code = 204
        return None
    approvals = [str(r.id) for r in conn.execute(text("SELECT id FROM job_approvals WHERE job_id = :j"), {"j": row.id})]
    issued = datetime.now(UTC)
    envelope = {
        "schema_version": "1.0", "job_id": str(row.id), "tenant_id": str(p.tenant_id), "edge_id": str(p.edge_id),
        "target_id": str(row.target_id), "operation": row.operation, "idempotency_key": row.idempotency_key,
        "issued_at": issued.isoformat(), "expires_at": row.expires_at.isoformat(), "nonce": row.nonce,
        "intent_sha256": row.intent_hash.strip(), "policy_version": POLICY_VERSION, "approval_ids": approvals,
    }
    bench_job = row.operation in bench.BENCH_OPS and _blocked_reason(row.operation) is not None
    if bench_job:
        # ADR-0030: the bench write names the ACS device the Edge must confirm (OUI/class/serial) and carries its single-use authorization,
        # the owner epoch and an end of validity that is never later than the authorization window; all covered by the signature
        auth = conn.execute(text("SELECT id, window_end FROM bench_authorizations WHERE job_id = :j"), {"j": row.id}).first()
        if auth is None or row.owner_epoch is None:
            cas(conn, row.id, "CANCELLED")
            response.status_code = 204
            return None
        envelope["authorization_id"], envelope["authorization_ends_at"] = str(auth.id), auth.window_end.isoformat()
        envelope["owner_epoch"] = row.owner_epoch
        # the envelope is also short-lived on its own (bench.ENVELOPE_TTL), so a copy that waits in transit or in a queue dies in minutes
        envelope["expires_at"] = min(row.expires_at, auth.window_end, issued + bench.ENVELOPE_TTL).isoformat()
    if (row.operation == "refresh" or bench_job) and row.target_type == "cpe":
        # The ACS device id the Edge may ask about (ADR-SD-002 item 4), covered by the signature. A CPE without a TR-069 binding keeps the
        # old behaviour (a plain collection round); the Edge validates the value again and only acts when active reads are enabled.
        ref = conn.execute(
            text("SELECT external_id FROM cpe_protocol_bindings WHERE cpe_id = :c AND protocol = 'tr069' "
                 "ORDER BY observed_at DESC NULLS LAST, id LIMIT 1"),
            {"c": row.target_id},
        ).scalar()
        if ref and TARGET_REF_RE.fullmatch(ref):
            envelope["target_ref"] = ref
        elif bench_job:  # a bench write without the device it must confirm cannot be sent
            cas(conn, row.id, "CANCELLED")
            response.status_code = 204
            return None
    envelope["signature"] = jobsign.sign(jobsign.load_private(settings.job_signing_key), envelope)
    if not cas(conn, row.id, "DISPATCHED"):  # the emission is the transition: no confirmed transition, no envelope leaves
        response.status_code = 204
        return None
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="job", aggregate_id=row.id, event_type="job.dispatched",
                   payload={"operation": row.operation, "edge_id": str(p.edge_id)})
    return envelope


class ResultIn(BaseModel):
    state: Literal["accepted", "succeeded", "failed"]
    detail: str | None = Field(default=None, max_length=500)
    postcheck_ok: bool = False


@router.post("/v1/edge/jobs/{job_id}/result", status_code=204)
def job_result(
    job_id: UUID, body: ResultIn, p: Principal = Depends(require("jobs:execute")), conn: Connection = TENANT_CONN
) -> None:
    row = _load(conn, job_id)
    if p.edge_id is None or row.edge_id != p.edge_id:
        raise HTTPException(403, "job belongs to another edge")
    to = {"accepted": "ACCEPTED", "failed": "FAILED"}.get(body.state) or ("SUCCEEDED" if body.postcheck_ok else "UNKNOWN")
    if row.status == to:
        return  # idempotent: the Edge re-sends a durable result until acknowledged; the same outcome is a no-op
    if not cas(conn, job_id, to, extra=", result = CAST(:res AS jsonb)",
               params={"res": json.dumps({"detail": body.detail, "postcheck_ok": body.postcheck_ok})}):
        raise HTTPException(409, f"illegal transition from {row.status} to {to}")
    if to in ("FAILED", "UNKNOWN") and row.operation in bench.BENCH_OPS and _blocked_reason(row.operation):
        bench.lock_target(conn, row.target_id, f"bench write ended {to}")  # no retry, no new write until `bench-unlock`
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="job", aggregate_id=job_id, event_type=f"job.{to.lower()}",
                   payload={"operation": row.operation})
