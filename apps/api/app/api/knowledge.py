"""Knowledge base (ADR-0041, PR5): read-only reference of the OLT vendors. Nothing here talks to an OLT and nothing is executable. Same gate as the Fleet Manager (`fleet:read` + flag `fleet_manager`)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Connection

from app.api.deps import TENANT_CONN, Principal, require
from app.core import features, knowledge

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
