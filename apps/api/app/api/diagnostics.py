"""Deterministic diagnostic rules (FC22-006): read-only execution over the inventory we already hold, persisted so it can be replayed.

A run NEVER touches equipment, opens an incident, or calls the network: it reads ONU state already collected, evaluates a versioned
PURE rule (app/core/diagnostics.py) and records the rule id + version, the exact inputs and the findings.
Customer data never enters a run."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.noc import DROP_WINDOW, EVAL_FRESH_FOR
from app.api.routes import audit
from app.core import diagnostics, features

router = APIRouter()

# a WAN reading older than this supports no claim; the verdict is STORED per reading (`fresh`), so a replay needs no clock
STATE_FRESH_FOR = timedelta(hours=1)
MAX_PONS = 200   # one run looks at most at this many PONs; a bigger scope is reported as truncated, never silently cut


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str = Field(pattern=r"^R-D[0-9]{3}$")
    rule_version: int | None = Field(None, ge=1)   # omitted = the latest registered version
    olt_id: UUID | None = None
    pon_id: UUID | None = None
    onu_id: UUID | None = None   # the PON of this ONU (resolved server-side); exclusive with olt_id/pon_id
    cpe_id: UUID | None = None   # for CPE rules (R-D002): the CPE; exclusive with olt_id/pon_id/onu_id

    @model_validator(mode="after")
    def _one_scope(self) -> RunRequest:
        if self.onu_id and (self.olt_id or self.pon_id):
            raise ValueError("onu_id cannot be combined with olt_id or pon_id")
        if self.cpe_id and (self.olt_id or self.pon_id or self.onu_id):
            raise ValueError("cpe_id cannot be combined with olt_id, pon_id or onu_id")
        return self


def _rule_view(r: diagnostics.Rule) -> dict:
    return {"id": r.id, "version": r.version, "title": r.title, "description": r.description, "subject": r.subject, "read_only": True}


@router.get("/v1/diagnostics/rules")
def list_rules(p: Principal = Depends(require("incidents:read")), conn: Connection = TENANT_CONN) -> list[dict]:
    features.ensure(conn, p.tenant_id, "diagnostic_engine")
    return [_rule_view(r) for _, r in sorted(diagnostics.RULES.items())]


def _pon_inputs(conn: Connection, olt_id: UUID | None, pon_id: UUID | None) -> tuple[list[dict], bool]:
    """One row per PON from the stored ONU state (RLS scopes the tenant). `reference_at` = the newest ONU observation of the PON: drops
    are 'recent' relative to it, and the data is 'fresh' only if it is within EVAL_FRESH_FOR of now.
    Both are stored: a replay needs no clock."""
    now = datetime.now(UTC)
    rows = conn.execute(
        text(
            "WITH pons AS (SELECT p.id, p.pon_path, p.olt_id FROM pon_ports p WHERE (CAST(:o AS uuid) IS NULL OR p.olt_id = :o) "
            "AND (CAST(:p AS uuid) IS NULL OR p.id = :p) ORDER BY p.pon_path, p.id LIMIT :n) "
            "SELECT p.id AS pon_id, p.pon_path, ol.name AS olt, g.ref, count(u.id) AS observed, "
            "count(*) FILTER (WHERE u.status = 'online') AS online, "
            "count(*) FILTER (WHERE u.status IN ('offline','los','dying_gasp') AND u.down_since IS NOT NULL "
            "                 AND u.down_since >= g.ref - make_interval(secs => :win)) AS recent_drops, "
            "count(*) FILTER (WHERE u.status = 'los' AND u.down_since IS NOT NULL "
            "                 AND u.down_since >= g.ref - make_interval(secs => :win)) AS los, "
            "count(*) FILTER (WHERE u.status = 'dying_gasp' AND u.down_since IS NOT NULL "
            "                 AND u.down_since >= g.ref - make_interval(secs => :win)) AS dying_gasp, "
            "count(*) FILTER (WHERE u.status IN ('offline','los','dying_gasp')) AS down "
            "FROM pons p JOIN olts ol ON ol.id = p.olt_id "
            "LEFT JOIN LATERAL (SELECT max(observed_at) AS ref FROM onus WHERE pon_id = p.id) g ON true "
            "LEFT JOIN onus u ON u.pon_id = p.id AND u.tenant_id = ol.tenant_id "
            "GROUP BY p.id, p.pon_path, ol.name, g.ref ORDER BY p.pon_path, p.id"
        ),
        {"o": olt_id, "p": pon_id, "n": MAX_PONS + 1, "win": DROP_WINDOW.total_seconds()},
    ).all()
    truncated = len(rows) > MAX_PONS
    out = []
    for r in rows[:MAX_PONS]:
        out.append({
            "subject_id": str(r.pon_id), "pon_path": r.pon_path, "olt": r.olt, "observed": r.observed, "online": r.online,
            "recent_drops": r.recent_drops, "los": r.los, "dying_gasp": r.dying_gasp, "chronic": r.down - r.recent_drops,
            "reference_at": r.ref.isoformat() if r.ref else None, "fresh_data": bool(r.ref and now - r.ref <= EVAL_FRESH_FOR),
        })
    return out, truncated


def _cpe_inputs(conn: Connection, cpe_id: UUID) -> list[dict]:
    """One row for the CPE from the stored state (RLS scopes the tenant). Per-reading freshness, the ages and the ONU freshness
    are STORED: the rule has no clock. Only enum words and numbers go in (no serial, no customer data)."""
    if conn.execute(text("SELECT 1 FROM cpes WHERE id = :c"), {"c": cpe_id}).first() is None:
        raise HTTPException(404, "cpe not found")
    now = datetime.now(UTC)
    st = conn.execute(text("SELECT metric, scope, value, captured_at FROM cpe_state WHERE cpe_id = :c AND metric IN "
                           "('wan_link_status','wan_connection_status') ORDER BY metric, scope"), {"c": cpe_id}).all()

    def age(r) -> int:
        return max(0, int((now - r.captured_at).total_seconds()))

    def fresh(r) -> bool:  # per reading: the cache keeps the last row of EVERY connection, one recent row must not vouch for an old one
        return age(r) <= STATE_FRESH_FOR.total_seconds()

    link = next((r for r in st if r.metric == "wan_link_status"), None)
    conns = sorted(({"state": r.value, "fresh": fresh(r)} for r in st if r.metric == "wan_connection_status"),
                   key=lambda c: (c["state"], c["fresh"]))
    ages = [age(r) for r in st]
    onu = conn.execute(
        text("SELECT o.status, o.observed_at FROM onu_cpe_links l JOIN onus o ON o.id = l.onu_id AND o.tenant_id = l.tenant_id "
             "WHERE l.cpe_id = :c AND l.status = 'confirmed'"), {"c": cpe_id}).first()
    return [{"subject_id": str(cpe_id), "wan_link": link.value if link else None, "wan_link_fresh": bool(link and fresh(link)),
             "connections": conns, "newest_age_seconds": min(ages, default=None), "oldest_age_seconds": max(ages, default=None),
             "onu_link": "confirmed" if onu else "none", "onu_status": onu.status if onu else None,
             "onu_fresh": bool(onu and onu.observed_at and now - onu.observed_at <= EVAL_FRESH_FOR)}]


@router.post("/v1/diagnostics/runs", status_code=201)
def create_run(body: RunRequest, p: Principal = Depends(require("diagnostics:run")), conn: Connection = TENANT_CONN) -> dict:
    features.ensure(conn, p.tenant_id, "diagnostic_engine")
    rule = diagnostics.RULES.get((body.rule_id, body.rule_version)) if body.rule_version else diagnostics.latest(body.rule_id)
    if rule is None:
        raise HTTPException(404, "rule not found")
    pon_id, cpe_id = body.pon_id, body.cpe_id
    if rule.subject == "cpe":
        if body.olt_id or body.pon_id:
            raise HTTPException(422, "this rule takes cpe_id or onu_id")
        if body.onu_id:  # RLS: another tenant's ONU is simply not found
            if conn.execute(text("SELECT 1 FROM onus WHERE id = :o"), {"o": body.onu_id}).first() is None:
                raise HTTPException(404, "onu not found")
            link = conn.execute(
                text("SELECT cpe_id FROM onu_cpe_links WHERE onu_id = :o AND status = 'confirmed'"), {"o": body.onu_id}).first()
            if link is None:
                raise HTTPException(409, "onu has no confirmed cpe link")
            cpe_id = link.cpe_id
        if cpe_id is None:
            raise HTTPException(422, "this rule needs cpe_id or onu_id")
        inputs, truncated = _cpe_inputs(conn, cpe_id), False
    else:
        if body.cpe_id:
            raise HTTPException(422, "this rule does not take cpe_id")
        if body.onu_id:
            # RLS: another tenant's ONU is simply not found
            row = conn.execute(text("SELECT pon_id FROM onus WHERE id = :o"), {"o": body.onu_id}).first()
            if row is None:
                raise HTTPException(404, "onu not found")
            if row.pon_id is None:
                raise HTTPException(409, "onu has no known PON")
            pon_id = row.pon_id
        inputs, truncated = _pon_inputs(conn, body.olt_id, pon_id)
    findings = diagnostics.run(rule, inputs)
    scope = {"olt_id": str(body.olt_id) if body.olt_id else None, "pon_id": str(pon_id) if pon_id else None,
             "onu_id": str(body.onu_id) if body.onu_id else None, **({"cpe_id": str(cpe_id)} if cpe_id else {})}
    run_id = conn.execute(
        text("INSERT INTO diagnostic_runs (tenant_id, rule_id, rule_version, scope, inputs, findings, truncated, requested_by) "
             "VALUES (:t,:r,:v,CAST(:s AS jsonb),CAST(:i AS jsonb),CAST(:f AS jsonb),:x,:u) RETURNING id"),
        {"t": p.tenant_id, "r": rule.id, "v": rule.version, "s": json.dumps(scope), "i": json.dumps(inputs), "f": json.dumps(findings),
         "x": truncated, "u": p.id},
    ).scalar_one()
    audit(conn, p, "diagnostics.run", "diagnostic_run", str(run_id), {"rule": rule.id, "version": rule.version, "subjects": len(inputs)})
    return {"run_id": str(run_id), "rule_id": rule.id, "rule_version": rule.version, "scope": scope, "truncated": truncated,
            "findings": findings}


@router.get("/v1/diagnostics/runs/{run_id}")
def get_run(run_id: UUID, p: Principal = Depends(require("incidents:read")), conn: Connection = TENANT_CONN) -> dict:
    """The stored run plus `reproducible`: re-evaluating the STORED inputs under the SAME rule version gives the stored findings
    (None if that version is no longer registered, which must never happen: versions are append-only)."""
    features.ensure(conn, p.tenant_id, "diagnostic_engine")
    r = conn.execute(
        text("SELECT id, rule_id, rule_version, scope, inputs, findings, truncated, created_at FROM diagnostic_runs WHERE id = :i"),
        {"i": run_id},
    ).first()
    if r is None:
        raise HTTPException(404, "run not found")
    rule = diagnostics.RULES.get((r.rule_id, r.rule_version))
    reproducible = None if rule is None else diagnostics.run(rule, r.inputs) == r.findings
    return {"run_id": str(r.id), "rule_id": r.rule_id, "rule_version": r.rule_version, "scope": r.scope, "truncated": r.truncated,
            "created_at": r.created_at.isoformat(), "findings": r.findings, "reproducible": reproducible}
