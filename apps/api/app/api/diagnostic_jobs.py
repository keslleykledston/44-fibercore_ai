"""Diagnostic jobs (SD-001 / ADR-0028): a passive, read-only, customer-centred diagnostic with evidence.

A job reads ONLY what the platform already holds (ONU state from the OLT snapshot, CPE state read from the ACS cache), runs the versioned
pure rules (R-D001 on the ONU's PON, R-D002 on the confirmed-linked CPE), and stores the evidence, the rule runs (rule + version + exact
inputs, so it replays) and the findings. It never touches equipment, never opens an incident and never writes state; it is append-only.
The work is a handful of indexed reads, so it completes inside the request; the receipt carries the real status."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.diagnostics import STATE_FRESH_FOR, _cpe_inputs, _pon_inputs
from app.api.noc import DROP_WINDOW, EVAL_FRESH_FOR
from app.api.routes import audit
from app.core import diagnostic_jobs, diagnostics, features

router = APIRouter()

MAX_ONUS = 10  # a customer with more ONUs is evaluated on the first ones and says so
SUPPORTED_DOMAINS = ("pon", "wan")  # the contract lists more (wifi, lan, internet, erp, bng): no data source for them yet
OpaqueRef = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
# the contract's OpaqueRef refuses a MAC-shaped value (pydantic's regex engine has no look-ahead)
MAC_LIKE = re.compile(r"^[0-9A-Fa-f]{2}([-:.]?[0-9A-Fa-f]{2}){5}$")


class CreateDiagnosticJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: UUID
    cpe_id: UUID | None = None
    mode: Literal["passive"]  # `guided` is in the contract but this PR only reads data already held
    requested_domains: list[Literal["pon", "wan"]] | None = Field(None, max_length=len(SUPPORTED_DOMAINS))
    ticket_id: OpaqueRef | None = None

    @field_validator("ticket_id")
    @classmethod
    def _not_a_mac(cls, v: str | None) -> str | None:
        if v is not None and MAC_LIKE.fullmatch(v):
            raise ValueError("ticket_id must be an opaque reference, not a hardware address")
        return v


def _normalised(body: CreateDiagnosticJob) -> dict:
    return {"customer_id": str(body.customer_id), "cpe_id": str(body.cpe_id) if body.cpe_id else None, "mode": body.mode,
            "requested_domains": sorted(set(body.requested_domains or SUPPORTED_DOMAINS)), "ticket_id": body.ticket_id}


def _ref(tenant, kind: str, ident) -> str:
    """Opaque, stable per tenant, reveals neither the serial nor the PON path (and is not MAC-shaped: it carries a word prefix)."""
    return f"{kind}-" + hashlib.sha256(f"{tenant}|{kind}|{ident}".encode()).hexdigest()[:16]


def _iso(v: datetime | None) -> str | None:
    return v.astimezone(UTC).isoformat().replace("+00:00", "Z") if v else None


def _cpe_states(conn: Connection, cpe_id: UUID, now: datetime) -> list[dict]:
    rows = conn.execute(
        text("SELECT metric, scope, value, captured_at, received_at FROM cpe_state WHERE cpe_id = :c ORDER BY metric, scope"),
        {"c": cpe_id})
    return [{"metric": r.metric, "scope": r.scope, "value": r.value, "captured_at": _iso(r.captured_at), "received_at": _iso(r.received_at),
             "fresh": now - r.captured_at <= STATE_FRESH_FOR} for r in rows]


def _evaluate(conn: Connection, req: dict, tenant) -> dict:
    now = datetime.now(UTC)
    cust = conn.execute(text("SELECT 1 FROM customers WHERE id = :c"), {"c": req["customer_id"]}).first()  # RLS: another tenant's is absent
    if cust is None:
        raise HTTPException(404, "customer not found")
    onus = conn.execute(
        text("SELECT u.id, u.pon_id, u.status, u.rx_dbm, u.observed_at, l.cpe_id AS linked_cpe FROM associations a "
             "JOIN onus u ON u.id = a.onu_id AND u.tenant_id = a.tenant_id "
             "LEFT JOIN onu_cpe_links l ON l.onu_id = u.id AND l.tenant_id = u.tenant_id AND l.status = 'confirmed' "
             "WHERE a.customer_id = :c AND a.status = 'approved' ORDER BY u.serial, u.id LIMIT :n"),
        {"c": req["customer_id"], "n": MAX_ONUS + 1}).all()
    truncated = len(onus) > MAX_ONUS
    onus = onus[:MAX_ONUS]
    if req["cpe_id"]:
        onus = [o for o in onus if o.linked_cpe is not None and str(o.linked_cpe) == req["cpe_id"]]
        if not onus:
            raise HTTPException(422, "cpe is not linked to an approved ONU of this customer")
    domains = req["requested_domains"]
    rule_runs: list[dict] = []
    done: dict[tuple, dict] = {}

    def run_rule(rule_id: str, subject_key: str, inputs: list[dict]) -> dict:
        key = (rule_id, subject_key)
        if key not in done:
            rule = diagnostics.latest(rule_id)
            findings = diagnostics.run(rule, inputs)
            rule_runs.append({"rule_id": rule.id, "rule_version": rule.version, "inputs": inputs, "findings": findings})
            done[key] = findings[0]
        return done[key]

    subjects = []
    for n, o in enumerate(onus, 1):
        fresh = bool(o.observed_at and now - o.observed_at <= EVAL_FRESH_FOR)
        rx = float(o.rx_dbm) if o.rx_dbm is not None else None
        s: dict = {"n": n, "onu": {"ref": _ref(tenant, "onu", o.id), "status": o.status, "rx_dbm": rx,
                                   "observed_at": _iso(o.observed_at), "fresh": fresh}, "pon_finding": None, "pon": None, "cpe": None}
        if "pon" in domains and o.pon_id is not None:
            inputs, _ = _pon_inputs(conn, None, o.pon_id)
            s["pon_finding"] = run_rule("R-D001", str(o.pon_id), inputs[:1]) if inputs else None
            if inputs:
                row = inputs[0]
                s["pon"] = {"ref": _ref(tenant, "pon", o.pon_id), "online": row["online"], "recent_drops": row["recent_drops"],
                            "window_seconds": int(DROP_WINDOW.total_seconds()),
                            "reference_at": _iso(
                    datetime.fromisoformat(row["reference_at"]) if row["reference_at"] else None), "fresh": row["fresh_data"]}
        if "wan" in domains and o.linked_cpe is not None:
            s["cpe"] = {"states": _cpe_states(conn, o.linked_cpe, now),
                        "finding": run_rule("R-D002", str(o.linked_cpe), _cpe_inputs(conn, o.linked_cpe))}
        subjects.append(s)
    out = diagnostic_jobs.assemble(subjects, domains, truncated)
    out["rule_runs"] = rule_runs
    return out


def _view(r) -> dict:
    return {"job_id": str(r.id), "run_id": None, "status": r.status, "data_quality": r.data_quality, "evidences": r.evidences,
            "findings": r.findings, "created_at": _iso(r.created_at), "completed_at": _iso(r.completed_at)}


COLS = "id, request_hash, status, data_quality, evidences, findings, rule_runs, created_at, completed_at"


@router.post("/v1/diagnostics/jobs", status_code=202)
def create_job(
    body: CreateDiagnosticJob,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$"),
    p: Principal = Depends(require("diagnostics:run")),
    conn: Connection = TENANT_CONN,
) -> dict:
    features.ensure(conn, p.tenant_id, "smart_diagnostics_jobs")
    features.ensure(conn, p.tenant_id, "diagnostic_engine")  # the job runs the engine's rules
    req = _normalised(body)
    h = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
    # one request per (user, key) at a time: a concurrent retry waits here and then finds the job instead of hitting the unique index
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"djob|{p.tenant_id}|{p.id}|{idempotency_key}"})
    existing = conn.execute(text(f"SELECT {COLS} FROM diagnostic_jobs WHERE requested_by = :u AND idempotency_key = :k"),  # noqa: S608
                            {"u": p.id, "k": idempotency_key}).first()
    if existing is not None:
        if existing.request_hash != h:
            raise HTTPException(409, "idempotency key reused with a different request")
        return {"job_id": str(existing.id), "status": existing.status, "created_at": _iso(existing.created_at)}
    out = _evaluate(conn, req, p.tenant_id)
    row = conn.execute(
        text("INSERT INTO diagnostic_jobs (tenant_id, requested_by, idempotency_key, request_hash, request, mode, status, data_quality, "
             "evidences, findings, rule_runs) VALUES (:t,:u,:k,:h,CAST(:rq AS jsonb),'passive',:s,:q,CAST(:e AS jsonb),CAST(:f AS jsonb),"
             "CAST(:r AS jsonb)) RETURNING id, request_hash, status, data_quality, evidences, findings, rule_runs, "
             "created_at, completed_at"),
        {"t": p.tenant_id, "u": p.id, "k": idempotency_key, "h": h, "rq": json.dumps(req), "s": out["status"], "q": out["data_quality"],
         "e": json.dumps(out["evidences"]), "f": json.dumps(out["findings"]), "r": json.dumps(out["rule_runs"])},
    ).one()
    audit(conn, p, "diagnostics.job.create", "diagnostic_job", str(row.id),
          {"customer_id": req["customer_id"], "status": row.status, "domains": req["requested_domains"]})
    return {"job_id": str(row.id), "status": row.status, "created_at": _iso(row.created_at)}


@router.get("/v1/diagnostics/jobs/{job_id}")
def get_job(job_id: UUID, p: Principal = Depends(require("incidents:read")), conn: Connection = TENANT_CONN) -> dict:
    """The stored job plus `reproducible`: re-evaluating each STORED rule run under the SAME rule version gives the stored findings
    (None if a version is no longer registered, which must never happen: versions are append-only)."""
    features.ensure(conn, p.tenant_id, "smart_diagnostics_jobs")
    features.ensure(conn, p.tenant_id, "diagnostic_engine")
    r = conn.execute(text(f"SELECT {COLS} FROM diagnostic_jobs WHERE id = :i"), {"i": job_id}).first()  # noqa: S608
    if r is None:
        raise HTTPException(404, "job not found")
    runs = [(diagnostics.RULES.get((x["rule_id"], x["rule_version"])), x) for x in r.rule_runs]
    reproducible = None if any(rule is None for rule, _ in runs) else all(
        diagnostics.run(rule, x["inputs"]) == x["findings"] for rule, x in runs)
    return {**_view(r), "reproducible": reproducible,
            "rule_runs": [{"rule_id": x["rule_id"], "rule_version": x["rule_version"]} for x in r.rule_runs]}
