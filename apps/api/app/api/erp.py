"""ERP hub (CSV first) and ONU<->customer association review.

Privacy (LGPD): the customer document is never stored in clear (HMAC + last4 only); logs/audit carry ids, not
names/documents. An association is only a SUGGESTION until a human with `associations:review` approves it.
Billing/contract status is data about the subscription, never evidence about the ONU state."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core.settings import Settings, get_settings
from app.events import outbox

router = APIRouter()

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,39}$")
REQUIRED = {"erp_customer_id", "display_name"}
OPTIONAL = {"document", "contract_status", "onu_serial", "source_updated_at"}
STATUSES = {"active", "suspended", "cancelled", "unknown"}
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _norm_doc(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def doc_hmac(key: str, tenant_id: UUID, digits: str) -> str:
    # tenant-scoped so the same person has unrelated digests in different tenants
    return hmac.new(key.encode(), f"{tenant_id}:{digits}".encode(), hashlib.sha256).hexdigest()


def _clean(v: str | None, max_len: int) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if CTRL.search(v) or len(v) > max_len:
        raise ValueError("invalid characters or too long")
    return v


@router.post("/v1/erp/import-csv")
async def import_csv(
    request: Request,
    source: str = Query(..., description="short id of the CSV origin, e.g. csv-manual"),
    p: Principal = Depends(require("customers:import")),
    conn: Connection = TENANT_CONN,
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.pii_hmac_key:
        raise HTTPException(503, "PII protection key not configured")  # fail closed
    if not SOURCE_RE.match(source):
        raise HTTPException(422, "invalid source id")
    declared = request.headers.get("content-length", "")
    if not declared.isdigit() or int(declared) > MAX_CSV_BYTES:
        raise HTTPException(413, "csv too large or missing Content-Length")
    chunks, size = [], 0
    async for chunk in request.stream():  # count while reading: never buffer past the limit
        size += len(chunk)
        if size > MAX_CSV_BYTES:
            raise HTTPException(413, "csv too large")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        text_in = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "csv must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text_in, newline=""), strict=True)
    cols = set(reader.fieldnames or [])
    if not REQUIRED <= cols or cols - REQUIRED - OPTIONAL:
        raise HTTPException(422, f"columns must include {sorted(REQUIRED)} and may include {sorted(OPTIONAL)} only")

    accepted, rejected, suggested, unmatched, conflicts = 0, [], 0, [], 0
    total = 0
    try:
        for n, row in enumerate(reader, start=2):
            total += 1
            if total > MAX_ROWS:
                raise HTTPException(413, f"more than {MAX_ROWS} rows")
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("wrong number of columns")
                ext_id = _clean(row["erp_customer_id"], 64)
                name = _clean(row["display_name"], 200)
                if not ext_id or not name:
                    raise ValueError("erp_customer_id and display_name are required")
                status = (_clean(row.get("contract_status"), 20) or "unknown").lower()
                if status not in STATUSES:
                    raise ValueError("contract_status invalid")
                digits = _norm_doc(row.get("document") or "")
                if digits and len(digits) not in (11, 14):
                    raise ValueError("document must have 11 or 14 digits")
                serial = _clean(row.get("onu_serial"), 64)
                updated = None
                if _clean(row.get("source_updated_at"), 40):
                    updated = datetime.fromisoformat(row["source_updated_at"].strip().replace("Z", "+00:00"))
                    if updated.tzinfo is None:
                        raise ValueError("source_updated_at needs timezone")
            except (ValueError, TypeError) as exc:
                rejected.append({"row": n, "reason": str(exc)})  # never echo the offending value (may be PII)
                continue
            cid = conn.execute(
                text(
                    "INSERT INTO customers (tenant_id, erp_source, erp_customer_id, display_name, document_hmac, document_last4, "
                    "contract_status, source_updated_at) VALUES (:t,:s,:e,:n,:h,:l,:c,:u) "
                    "ON CONFLICT (tenant_id, erp_source, erp_customer_id) DO UPDATE SET display_name=EXCLUDED.display_name, "
                    "document_hmac=COALESCE(EXCLUDED.document_hmac, customers.document_hmac), "
                    "document_last4=COALESCE(EXCLUDED.document_last4, customers.document_last4), "
                    "contract_status=EXCLUDED.contract_status, source_updated_at=EXCLUDED.source_updated_at "
                    "WHERE customers.source_updated_at IS NULL OR EXCLUDED.source_updated_at IS NULL "
                    "OR customers.source_updated_at <= EXCLUDED.source_updated_at RETURNING id"
                ),
                {"t": p.tenant_id, "s": source, "e": ext_id, "n": name,
                 "h": doc_hmac(settings.pii_hmac_key, p.tenant_id, digits) if digits else None,
                 "l": digits[-4:] if digits else None, "c": status, "u": updated},
            ).scalar_one_or_none()
            if cid is None:  # older than what we hold: ignored, but still counts as processed
                cid = conn.execute(
                    text("SELECT id FROM customers WHERE erp_source=:s AND erp_customer_id=:e"), {"s": source, "e": ext_id}
                ).scalar_one()
            accepted += 1
            if serial:
                res = _suggest(conn, p.tenant_id, cid, serial)
                if res == "unmatched":
                    unmatched.append({"row": n})
                elif res == "suggested":
                    suggested += 1
                elif res == "conflict":
                    suggested += 1
                    conflicts += 1
    except csv.Error as exc:
        raise HTTPException(422, f"malformed csv: {exc}") from exc
    batch_id = conn.execute(
        text("INSERT INTO import_batches (tenant_id, source, actor_id, rows_total, rows_accepted, rows_rejected) "
             "VALUES (:t,:s,:a,:rt,:ra,:rr) RETURNING id"),
        {"t": p.tenant_id, "s": source, "a": p.id, "rt": total, "ra": accepted, "rr": len(rejected)},
    ).scalar_one()
    audit(conn, p, "erp.import_csv", "import_batch", str(batch_id),
          {"source": source, "rows": total, "accepted": accepted, "rejected": len(rejected)})
    return {"batch_id": str(batch_id), "rows": total, "accepted": accepted, "rejected": rejected[:100],
            "rejected_count": len(rejected), "suggestions": suggested, "conflicts": conflicts, "unmatched_rows": unmatched[:100]}


def _suggest(conn: Connection, tenant_id: UUID, customer_id: UUID, serial: str) -> Literal["suggested", "conflict", "unmatched", "exists"]:
    serial_u = serial.upper()
    onus = conn.execute(text("SELECT id FROM onus WHERE upper(serial) = :s"), {"s": serial_u}).all()
    if not onus:
        return "unmatched"
    cpe_id = conn.execute(text("SELECT id FROM cpes WHERE upper(canonical_serial) = :s"), {"s": serial_u}).scalar_one_or_none()
    ambiguous = len(onus) > 1  # same serial seen on several OLTs: needs a human decision
    result: Literal["suggested", "conflict"] = "conflict" if ambiguous else "suggested"
    for (onu_id,) in onus:
        other = conn.execute(
            text("SELECT customer_id FROM associations WHERE onu_id=:o AND status='approved' AND customer_id <> :c"),
            {"o": onu_id, "c": customer_id},
        ).scalar_one_or_none()
        evidence = {"match": "serial_exact", "source": "csv", "ambiguous_serial": ambiguous,
                    "conflicts_with_approved": str(other) if other else None}
        if other:
            result = "conflict"
        inserted = conn.execute(
            text(
                "INSERT INTO associations (tenant_id, onu_id, cpe_id, customer_id, score, evidence) "
                "VALUES (:t,:o,:cp,:c,:sc,CAST(:ev AS jsonb)) ON CONFLICT (tenant_id, onu_id, customer_id) "
                "WHERE status <> 'rejected' DO NOTHING RETURNING id"
            ),
            {"t": tenant_id, "o": onu_id, "cp": cpe_id, "c": customer_id,
             "sc": 50 if (ambiguous or other) else 95, "ev": json.dumps(evidence)},
        ).first()
        if inserted is None:
            result = result if result == "conflict" else "suggested"
    return result


@router.get("/v1/customers")
def list_customers(
    limit: int = Query(100, ge=1, le=1000),
    p: Principal = Depends(require("customers:read")),
    conn: Connection = TENANT_CONN,
) -> list[dict]:
    rows = conn.execute(
        text("SELECT id, erp_source, erp_customer_id, display_name, document_last4, contract_status FROM customers "
             "ORDER BY display_name LIMIT :l"),
        {"l": limit},
    )
    audit(conn, p, "customers.list", "customer", "*", {"limit": limit})  # access to personal data is logged
    return [{"id": str(r.id), "erp_source": r.erp_source, "erp_customer_id": r.erp_customer_id,
             "display_name": r.display_name, "document_last4": r.document_last4, "contract_status": r.contract_status}
            for r in rows]


@router.get("/v1/associations")
def list_associations(
    status: Literal["suggested", "approved", "rejected"] | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=1_000_000),
    p: Principal = Depends(require("customers:read")),
    conn: Connection = TENANT_CONN,
) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT a.id, a.status, a.score, a.evidence, a.created_at, a.onu_id, u.serial, a.customer_id, c.display_name "
            "FROM associations a JOIN onus u ON u.id = a.onu_id AND u.tenant_id = a.tenant_id "
            "JOIN customers c ON c.id = a.customer_id AND c.tenant_id = a.tenant_id "
            "WHERE (CAST(:s AS text) IS NULL OR a.status = :s) ORDER BY a.created_at DESC, a.id LIMIT :l OFFSET :o"
        ),
        {"s": status, "l": limit, "o": offset},
    )
    return [{"id": str(r.id), "status": r.status, "score": float(r.score), "evidence": r.evidence,
             "onu_id": str(r.onu_id), "onu_serial": r.serial, "customer_id": str(r.customer_id),
             "customer_name": r.display_name, "created_at": r.created_at.isoformat()} for r in rows]


def _review(conn: Connection, p: Principal, assoc_id: UUID, new_status: str) -> dict:
    row = conn.execute(
        text("SELECT id, status, onu_id, customer_id, evidence FROM associations WHERE id = :i FOR UPDATE"), {"i": assoc_id}
    ).first()
    if row is None:
        raise HTTPException(404, "association not found")
    if row.status != "suggested":
        raise HTTPException(409, f"association already {row.status}")
    if new_status == "approved":
        # Serialise decisions per ONU: concurrent approvals of different candidates queue up here.
        conn.execute(text("SELECT 1 FROM onus WHERE id = :o FOR UPDATE"), {"o": row.onu_id})
        if (row.evidence or {}).get("ambiguous_serial"):
            raise HTTPException(409, "ambiguous serial across OLTs: reject duplicates or fix inventory first")
        existing = conn.execute(
            text("SELECT 1 FROM associations WHERE onu_id=:o AND status='approved'"), {"o": row.onu_id}
        ).first()
        if existing:
            raise HTTPException(409, "onu already has an approved association; reject it first")
    try:
        with conn.begin_nested():  # savepoint: a unique violation must not poison the outer transaction
            conn.execute(
                text("UPDATE associations SET status=:s, reviewed_by=:u, reviewed_at=now() WHERE id=:i"),
                {"s": new_status, "u": p.id, "i": assoc_id},
            )
    except IntegrityError as exc:  # the unique index is the last line of defence against double approval
        raise HTTPException(409, "onu already has an approved association") from exc
    audit(conn, p, f"association.{new_status}", "association", str(assoc_id), {"onu_id": str(row.onu_id)})
    outbox.enqueue(conn, tenant_id=p.tenant_id, aggregate_type="association", aggregate_id=assoc_id,
                   event_type=f"association.{new_status}", payload={"onu_id": str(row.onu_id), "customer_id": str(row.customer_id)})
    return {"id": str(assoc_id), "status": new_status}


@router.post("/v1/associations/{assoc_id}/approve")
def approve(assoc_id: UUID, p: Principal = Depends(require("associations:review")), conn: Connection = TENANT_CONN) -> dict:
    return _review(conn, p, assoc_id, "approved")


@router.post("/v1/associations/{assoc_id}/reject")
def reject(assoc_id: UUID, p: Principal = Depends(require("associations:review")), conn: Connection = TENANT_CONN) -> dict:
    return _review(conn, p, assoc_id, "rejected")


