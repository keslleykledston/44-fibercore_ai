"""Who may run queries on an OLT, and for how long (ADR-0029 item 3): the signed lease and the two-phase transfer.

The lease is the cloud's statement, renewed on every poll answer, of the OLTs this Edge owns RIGHT NOW with the epoch each envelope must repeat. It is signed
with the same key as the envelopes under its own schema name (`olt-lease/1`), so a bench lease can never pass for it. It lives in the Edge's memory only.
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, text

from app.core import features, jobsign, olt_query
from app.core.settings import Settings

LEASE_TTL = timedelta(minutes=2)      # the Edge honours a lease for at most this long after receiving it
CLOCK_MARGIN = timedelta(seconds=60)  # extra wait before a transfer may finish after the last lease issued to the old owner
SCHEMA = "olt-lease/1"


def lease_targets(conn: Connection, tenant_id: UUID, edge_id: UUID) -> list[dict]:
    """The OLTs this Edge may run queries on now: none unless the channel exists and the tenant flag is on; none that is mid-transfer."""
    if not olt_query.EDGE_SUPPORT or not features.enabled(conn, tenant_id, "olt_query"):
        return []
    rows = conn.execute(
        text("SELECT id, owner_epoch FROM olts WHERE edge_id = :e AND transfer_to IS NULL ORDER BY id"), {"e": edge_id}).all()
    return [{"target_ref": str(r.id), "owner_epoch": r.owner_epoch} for r in rows]


def issue(conn: Connection, tenant_id: UUID, edge_id: UUID, settings: Settings) -> str | None:
    """Signed lease for the poll answer (None = none: the Edge then drops what it holds). Records, per OLT, the last instant it was leased (server clock)."""
    targets = lease_targets(conn, tenant_id, edge_id)
    if not targets:
        return None
    issued = datetime.now(UTC)
    until = issued + LEASE_TTL
    conn.execute(text("UPDATE olts SET lease_until = :u WHERE id = ANY(:ids) AND transfer_to IS NULL AND (lease_until IS NULL OR lease_until < :u)"),
                 {"u": until, "ids": [UUID(t["target_ref"]) for t in targets]})
    body = {"schema": SCHEMA, "tenant_id": str(tenant_id), "edge_id": str(edge_id), "issued_at": issued.replace(microsecond=0).isoformat(),
            "expires_at": until.replace(microsecond=0).isoformat(), "targets": targets}
    body["signature"] = jobsign.sign(jobsign.load_private(settings.job_signing_key), body)
    return base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()
