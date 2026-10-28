from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import Connection, text


def enqueue(
    conn: Connection,
    *,
    tenant_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    payload: dict,
    schema_version: str = "1",
) -> UUID:
    """Insert an event in the SAME transaction as the state change (transactional outbox)."""
    return conn.execute(
        text(
            "INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
            "VALUES (:t, :at, :ai, :et, :sv, CAST(:p AS jsonb)) RETURNING id"
        ),
        {"t": tenant_id, "at": aggregate_type, "ai": aggregate_id, "et": event_type, "sv": schema_version,
         "p": json.dumps(payload)},
    ).scalar_one()
