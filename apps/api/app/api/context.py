"""ONU<->CPE links (evidence + human confirmation) and the read-only Customer Context (ADR-0021, FC22-004).

Nothing here writes to the network. The ONU is seen by the OLT and the CPE by the ACS: different sources, different identities. A link is a
CLAIM with evidence; string equality of serials is only a hint (`serial_equal`, low confidence), never proof, and a person confirms it.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import TENANT_CONN, Principal, require
from app.api.inventory import _prov
from app.api.routes import audit
from app.core import features
from app.events import outbox

router = APIRouter()

ERP_FRESH_FOR = timedelta(days=7)   # ASSUMPTION (to be approved): ERP imports are batch jobs, not minute-level telemetry
SUGGEST_LIMIT = 1000
SUGGESTIONS_SHOWN = 10             # per ONU; the true count and `has_more_suggestions` are always reported
CONTEXT_ONU_LIMIT = 50              # a customer with more approved ONUs is reported as truncated, never silently cut
CONF_SERIAL_EQUAL = 0.50            # equality of serials is only an indication
CONF_SERIAL_EQUAL_AMBIGUOUS = 0.20  # the same ONU serial exists on more than one OLT


def _link_view(r) -> dict:
    return {"id": str(r.id), "status": r.status, "confidence": float(r.confidence), "evidence": r.evidence,
            "onu": {"id": str(r.onu_id), "serial": r.onu_serial}, "cpe": {"id": str(r.cpe_id), "canonical_serial": r.cpe_serial},
            "created_at": r.created_at.isoformat(), "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None}


LINK_SELECT = (
    "SELECT l.id, l.status, l.confidence, l.evidence, l.onu_id, l.cpe_id, l.created_at, l.reviewed_at, u.serial AS onu_serial, "
    "c.canonical_serial AS cpe_serial FROM onu_cpe_links l JOIN onus u ON u.id = l.onu_id AND u.tenant_id = l.tenant_id "
    "JOIN cpes c ON c.id = l.cpe_id AND c.tenant_id = l.tenant_id"
)


@router.post("/v1/onu-cpe-links/suggest", status_code=201)
def suggest_links(p: Principal = Depends(require("associations:review")), conn: Connection = TENANT_CONN) -> dict:
    """Creates SUGGESTED links where an ONU serial equals a CPE serial. Idempotent. Suggestions never become confirmed by themselves."""
    features.ensure(conn, p.tenant_id, "onu_cpe_links")
    rows = conn.execute(
        text(
            "SELECT u.id AS onu_id, c.id AS cpe_id, "
            "(SELECT count(*) FROM onus u2 WHERE upper(btrim(u2.serial)) = upper(btrim(u.serial))) AS same_serial_onus "
            "FROM onus u JOIN cpes c ON upper(btrim(u.serial)) = c.canonical_serial "
            "WHERE NOT EXISTS (SELECT 1 FROM onu_cpe_links l WHERE l.onu_id = u.id AND l.cpe_id = c.id) "
            "ORDER BY u.serial, u.id LIMIT :n"
        ),
        {"n": SUGGEST_LIMIT},
    ).all()
    created = 0
    for r in rows:
        amb = r.same_serial_onus > 1
        evidence = {"rule": "serial_equal", "ambiguous": amb,
                    "note": "ONU and CPE serials are equal; equality is an indication, not proof"}
        done = conn.execute(
            text("INSERT INTO onu_cpe_links (tenant_id, onu_id, cpe_id, confidence, evidence) VALUES (:t,:o,:c,:k,CAST(:e AS jsonb)) "
                 "ON CONFLICT DO NOTHING RETURNING id"),
            {"t": p.tenant_id, "o": r.onu_id, "c": r.cpe_id, "k": CONF_SERIAL_EQUAL_AMBIGUOUS if amb else CONF_SERIAL_EQUAL,
             "e": json.dumps(evidence)},
        ).first()
        created += 1 if done else 0
    audit(conn, p, "onu_cpe_links.suggest", "onu_cpe_link", "*", {"created": created})
    return {"created": created, "examined": len(rows), "limit_reached": len(rows) == SUGGEST_LIMIT}


@router.get("/v1/onu-cpe-links")
def list_links(
    status: Literal["suggested", "confirmed", "rejected"] | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=1_000_000),
    p: Principal = Depends(require("inventory:read")),
    conn: Connection = TENANT_CONN,
) -> list[dict]:
    features.ensure(conn, p.tenant_id, "onu_cpe_links")
    rows = conn.execute(
        text(LINK_SELECT + " WHERE (CAST(:s AS text) IS NULL OR l.status = :s) ORDER BY l.created_at DESC, l.id LIMIT :l OFFSET :o"),  # noqa: S608
        {"s": status, "l": limit, "o": offset},
    )
    return [_link_view(r) for r in rows]


def _review(conn: Connection, p: Principal, link_id: UUID, new_status: str) -> dict:
    features.ensure(conn, p.tenant_id, "onu_cpe_links")
    row = conn.execute(
        text("SELECT id, status, onu_id, cpe_id, evidence FROM onu_cpe_links WHERE id = :i FOR UPDATE"), {"i": link_id}
    ).first()
    if row is None:
        raise HTTPException(404, "link not found")
    if row.status != "suggested":
        raise HTTPException(409, f"link already {row.status}")
    if new_status == "confirmed":
        if (row.evidence or {}).get("ambiguous"):
            raise HTTPException(409, "ambiguous: the ONU serial exists on more than one OLT; resolve the inventory first")
        clash = conn.execute(
            text("SELECT 1 FROM onu_cpe_links WHERE status = 'confirmed' AND (onu_id = :o OR cpe_id = :c)"),
            {"o": row.onu_id, "c": row.cpe_id},
        ).first()
        if clash:
            raise HTTPException(409, "the ONU or the CPE already has a confirmed link")
    try:
        with conn.begin_nested():  # savepoint: the unique indexes are the last line of defence against a concurrent confirmation
            conn.execute(text("UPDATE onu_cpe_links SET status = :s, reviewed_by = :u, reviewed_at = now() WHERE id = :i"),
                         {"s": new_status, "u": p.id, "i": link_id})
    except IntegrityError as exc:
        raise HTTPException(409, "the ONU or the CPE already has a confirmed link") from exc
    audit(conn, p, f"onu_cpe_link.{new_status}", "onu_cpe_link", str(link_id), {"onu_id": str(row.onu_id), "cpe_id": str(row.cpe_id)})
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="onu_cpe_link", aggregate_id=link_id,
                   event_type=f"onu_cpe_link.{new_status}", payload={"onu_id": str(row.onu_id), "cpe_id": str(row.cpe_id)})
    return {"id": str(link_id), "status": new_status}


@router.post("/v1/onu-cpe-links/{link_id}/confirm")
def confirm_link(link_id: UUID, p: Principal = Depends(require("associations:review")), conn: Connection = TENANT_CONN) -> dict:
    return _review(conn, p, link_id, "confirmed")


@router.post("/v1/onu-cpe-links/{link_id}/reject")
def reject_link(link_id: UUID, p: Principal = Depends(require("associations:review")), conn: Connection = TENANT_CONN) -> dict:
    return _review(conn, p, link_id, "rejected")


def cpe_blocks(conn: Connection, tenant_id: UUID, onu_ids: list[UUID], can_review: bool = False) -> dict[UUID, dict]:
    """The CPE of each ONU as the context shows it (link: confirmed | suggested | none | unavailable when the flag is off).
    Constant number of queries however many ONUs: flag once, confirmed links once, suggestions once.
    `suggestions` (ids + evidence, no device identifiers) lets the UI offer confirm/reject; `can_review` says whether the role may."""
    if not features.enabled(conn, tenant_id, "onu_cpe_links"):
        off = {"link": "unavailable", "pending_suggestions": 0, "suggestions": [], "has_more_suggestions": False, "can_review": False,
               "device": None, "provenance": None}
        return {i: off for i in onu_ids}
    confirmed = {
        r.onu_id: r for r in conn.execute(
            text("SELECT l.onu_id, c.id, c.vendor, c.model, c.firmware, c.observed_at, "
                 "COALESCE((SELECT array_agg(DISTINCT b.protocol ORDER BY b.protocol) FROM cpe_protocol_bindings b WHERE b.cpe_id = c.id "
                 "AND b.tenant_id = c.tenant_id), ARRAY[]::text[]) AS protocols "
                 "FROM onu_cpe_links l JOIN cpes c ON c.id = l.cpe_id AND c.tenant_id = l.tenant_id "
                 "WHERE l.onu_id = ANY(:ids) AND l.status = 'confirmed'"),
            {"ids": onu_ids})
    }
    pending: dict[UUID, list[dict]] = {}
    pending_total: dict[UUID, int] = {}
    for r in conn.execute(
        text("SELECT l.onu_id, l.id, l.confidence, l.evidence FROM onu_cpe_links l WHERE l.onu_id = ANY(:ids) AND l.status = 'suggested' "
             "ORDER BY l.onu_id, l.confidence DESC, l.id"),
        {"ids": onu_ids},
    ):
        bucket = pending.setdefault(r.onu_id, [])
        pending_total[r.onu_id] = pending_total.get(r.onu_id, 0) + 1  # the TRUE count; only the items shown are capped
        if len(bucket) < SUGGESTIONS_SHOWN:
            bucket.append({"id": str(r.id), "confidence": float(r.confidence), "rule": (r.evidence or {}).get("rule"),
                           "ambiguous": bool((r.evidence or {}).get("ambiguous"))})
    out: dict[UUID, dict] = {}
    for i in onu_ids:
        c = confirmed.get(i)
        if c is not None:
            out[i] = {"link": "confirmed", "pending_suggestions": 0, "suggestions": [], "has_more_suggestions": False,
                      "can_review": can_review,
                      "device": {"id": str(c.id), "vendor": c.vendor, "model": c.model, "firmware": c.firmware,
                                 "protocols": list(c.protocols)},
                      "provenance": _prov("genieacs_nbi", c.observed_at)}
        else:
            sug = pending.get(i, [])
            total = pending_total.get(i, 0)
            out[i] = {"link": "suggested" if sug else "none", "pending_suggestions": total, "suggestions": sug,
                      "has_more_suggestions": total > len(sug), "can_review": can_review, "device": None, "provenance": None}
    return out


def cpe_block(conn: Connection, tenant_id: UUID, onu_id: UUID, can_review: bool = False) -> dict:
    return cpe_blocks(conn, tenant_id, [onu_id], can_review)[onu_id]


@router.get("/v1/customers/{customer_id}/context")
def customer_context(customer_id: UUID, p: Principal = Depends(require("customers:read")), conn: Connection = TENANT_CONN) -> dict:
    """Read-only 360 of ONE customer: contract + the ONU(s) a person approved + each ONU's CPE link, every block with source/time/quality.
    status: unknown (no approved ONU) > stale (any block not fresh) > partial (some ONU without a confirmed CPE) > complete."""
    features.ensure(conn, p.tenant_id, "customer_context")
    cu = conn.execute(
        text("SELECT erp_source, display_name, document_last4, contract_status, source_updated_at, created_at "
             "FROM customers WHERE id = :i"),
        {"i": customer_id},
    ).first()
    if cu is None:
        raise HTTPException(404, "customer not found")
    can_incidents = p.can("incidents:read")
    onus = conn.execute(
        text(
            "SELECT u.id, u.serial, u.status, u.rx_dbm, u.observed_at, o.name AS olt_name, o.observed_at AS olt_observed_at, pp.pon_path, "
            "(SELECT i.suspected_cause FROM incident_onus io JOIN incidents i ON i.id = io.incident_id AND i.tenant_id = io.tenant_id "
            " WHERE io.onu_id = u.id AND i.status = 'open' ORDER BY i.opened_at DESC LIMIT 1) AS cause "
            "FROM associations a JOIN onus u ON u.id = a.onu_id AND u.tenant_id = a.tenant_id "
            "JOIN olts o ON o.id = u.olt_id AND o.tenant_id = u.tenant_id "
            "LEFT JOIN pon_ports pp ON pp.id = u.pon_id AND pp.tenant_id = u.tenant_id "
            "WHERE a.customer_id = :c AND a.status = 'approved' ORDER BY u.serial LIMIT :n"
        ),
        {"c": customer_id, "n": CONTEXT_ONU_LIMIT + 1},
    ).all()
    truncated = len(onus) > CONTEXT_ONU_LIMIT
    onus = onus[:CONTEXT_ONU_LIMIT]
    blocks = cpe_blocks(conn, p.tenant_id, [u.id for u in onus], p.can("associations:review"))
    out_onus, qualities, unlinked = [], [], False
    for u in onus:
        cb = blocks[u.id]
        pv = _prov("olt_snapshot", u.observed_at)
        qualities.append(pv["quality"])
        if cb["provenance"]:
            qualities.append(cb["provenance"]["quality"])
        unlinked = unlinked or cb["link"] != "confirmed"
        out_onus.append({
            "id": str(u.id), "serial": u.serial, "status": u.status, "rx_dbm": float(u.rx_dbm) if u.rx_dbm is not None else None,
            "olt": u.olt_name, "pon_path": u.pon_path, "provenance": pv,
            "incident": ({"suspected_cause": u.cause} if (can_incidents and u.cause) else None), "incident_hidden": not can_incidents,
            "cpe": cb,
        })
    erp = _prov(f"erp:{cu.erp_source}", cu.source_updated_at or cu.created_at, ERP_FRESH_FOR)
    qualities.append(erp["quality"])
    status = ("unknown" if not onus else "stale" if any(q != "fresh" for q in qualities)
              else "partial" if (unlinked or truncated) else "complete")  # ONUs we did not look at cannot be called complete
    audit(conn, p, "customer.context.view", "customer", str(customer_id), {})  # personal data: every view is audited
    return {"customer_id": str(customer_id), "status": status, "onus_truncated": truncated,
            "customer": {"display_name": cu.display_name, "document_last4": cu.document_last4, "contract_status": cu.contract_status,
                         "provenance": erp},
            "onus": out_onus}
