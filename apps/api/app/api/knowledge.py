"""Knowledge base (ADR-0041, PR5): read-only reference of the OLT vendors. Nothing here talks to an OLT and nothing is executable. Same gate as the Fleet Manager (`fleet:read` + flag `fleet_manager`)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.core import features, homologation, knowledge

router = APIRouter()


def _base() -> dict:
    try:
        return knowledge.load()
    except (knowledge.KnowledgeInvalid, KeyError, ValueError, OSError) as exc:   # a broken base is refused whole: it never shows half-checked
        raise HTTPException(503, "knowledge_base_invalid") from exc


@router.get("/v1/knowledge")
def index(p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    features.ensure(conn, p.tenant_id, "fleet_manager")
    b = _base()
    return {"sections": {s: len(b[s].get("items", b[s].get("matrix", []))) for s in knowledge.SECTIONS}}


@router.get("/v1/knowledge/{section}")
def section(section: str, p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    features.ensure(conn, p.tenant_id, "fleet_manager")
    if section not in knowledge.SECTIONS:
        raise HTTPException(404, "unknown section")
    return _base()[section]


OLT_LIMIT = 500        # the panel lists up to this many OLTs and SAYS when there are more
STALE_AFTER_MIN = 60   # the Edge collects every 15-20 minutes; an hour without a read is shown as stale, never as "up"


@router.get("/v1/fleet/homologation")
def homologation_matrix(p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    """The level (L0..L4) of each OLT model+firmware, computed from evidence, with the registered OLTs and what was seen of them. Read-only."""
    features.ensure(conn, p.tenant_id, "fleet_manager")
    try:
        led = homologation.load()
    except (homologation.LedgerInvalid, KeyError, ValueError, OSError) as exc:
        raise HTTPException(503, "homologation_ledger_invalid") from exc
    olts = conn.execute(text("SELECT name, vendor, model, firmware, support_level, observed_at, EXTRACT(EPOCH FROM (now() - observed_at)) AS age FROM olts WHERE tenant_id = :t ORDER BY name LIMIT :n"), {"t": p.tenant_id, "n": OLT_LIMIT}).all()
    olts_total = conn.execute(text("SELECT count(*) FROM olts WHERE tenant_id = :t"), {"t": p.tenant_id}).scalar_one()
    tests = {r.outcome: r.n for r in conn.execute(text("SELECT outcome, count(*) AS n FROM olt_connection_tests WHERE tenant_id = :t AND requested_at > now() - interval '24 hours' GROUP BY outcome"), {"t": p.tenant_id}).all()}   # explicit tenant filter on top of RLS
    live = []
    for o in olts:
        match = next((d for d in led["items"] if d["vendor"] == (o.vendor or "").lower() and d["model"] == (o.model or "") and d["firmware"] == (o.firmware or "")), None)
        live.append({"name": o.name, "vendor": o.vendor, "model": o.model, "firmware": o.firmware, "support_level": o.support_level,
                     "level": match["level"] if match else ("não catalogado" if o.model else "ainda não lida"),
                     "age_seconds": int(o.age) if o.age is not None else None, "stale": o.age is None or o.age > STALE_AFTER_MIN * 60})
    return {"levels": led["levels"], "devices": led["items"], "olts": live, "olts_total": olts_total, "olts_truncated": olts_total > len(live), "connection_tests_24h": tests, "stale_after_minutes": STALE_AFTER_MIN}
