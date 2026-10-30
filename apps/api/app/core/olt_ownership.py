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
MAX_SKEW = timedelta(seconds=45)      # the Edge refuses a lease whose issued_at is further than this from its own clock (so CLOCK_MARGIN covers the skew it can have)
SCHEMA = "olt-lease/1"


def lease_targets(conn: Connection, tenant_id: UUID, edge_id: UUID) -> list[dict]:
    """The OLTs this Edge may run queries on now: none unless the channel exists and the tenant flag is on; none that is mid-transfer."""
    if not olt_query.EDGE_SUPPORT or not features.enabled(conn, tenant_id, "olt_query"):
        return []
    rows = conn.execute(
        text("SELECT id, owner_epoch FROM olts WHERE edge_id = :e AND transfer_to IS NULL ORDER BY id"), {"e": edge_id}).all()
    return [{"target_ref": str(r.id), "owner_epoch": r.owner_epoch} for r in rows]


def issue(conn: Connection, tenant_id: UUID, edge_id: UUID, settings: Settings) -> str | None:
    """Signed lease for the poll answer (None = none: the Edge then drops what it holds).

    The instant the lease ends is computed ONCE, in whole seconds, and is the very value that is signed and the value recorded as `lease_until`, so the
    record is never earlier than what the Edge can honour. An OLT is leased only if recording it succeeded: a transfer that started a moment ago (its row is
    locked, then no longer eligible) takes the OLT out of this lease instead of leaving a lease nobody recorded. The Edge accepts a lease only when its own
    clock is within MAX_SKEW of `issued_at`, which is what makes CLOCK_MARGIN (> MAX_SKEW) enough for the transfer to wait."""
    targets = lease_targets(conn, tenant_id, edge_id)
    if not targets:
        return None
    issued = datetime.now(UTC).replace(microsecond=0)
    until = issued + LEASE_TTL
    ok = {r.id for r in conn.execute(
        text("UPDATE olts SET lease_until = GREATEST(COALESCE(lease_until, :u), :u) WHERE id = ANY(:ids) AND edge_id = :e AND transfer_to IS NULL RETURNING id"),
        {"u": until, "ids": [UUID(t["target_ref"]) for t in targets], "e": edge_id})}
    targets = [t for t in targets if UUID(t["target_ref"]) in ok]
    if not targets:
        return None
    body = {"schema": SCHEMA, "tenant_id": str(tenant_id), "edge_id": str(edge_id), "issued_at": issued.isoformat(),
            "expires_at": until.isoformat(), "targets": targets}
    body["signature"] = jobsign.sign(jobsign.load_private(settings.job_signing_key), body)
    return base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()
