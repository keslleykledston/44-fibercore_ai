"""Outbox relay: publishes unpublished events to JetStream, then marks them published.

At-least-once by design: a crash between publish and mark re-publishes on restart; the
Nats-Msg-Id header (= outbox id) lets JetStream drop the duplicate. Runs as role
`fibercore_worker` (read outbox + UPDATE published_at only).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.db import make_engine
from app.events import bus

log = logging.getLogger("relay")


async def relay_once(engine: Engine, js, *, batch: int = 100, crash_after_publish: bool = False) -> int:
    """Publish up to `batch` events. Returns how many were marked published.

    `crash_after_publish` is a test hook simulating a process crash before the DB mark.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT tenant_id, id, replay_gen, event_type, aggregate_type, aggregate_id, schema_version, payload, created_at "
                "FROM events_outbox WHERE published_at IS NULL ORDER BY created_at, id LIMIT :n FOR UPDATE SKIP LOCKED"
            ),
            {"n": batch},
        ).all()
        done: list = []
        for r in rows:
            envelope = {
                "id": str(r.id),
                "tenant_id": str(r.tenant_id),
                "type": r.event_type,
                "schema_version": r.schema_version,
                "aggregate": {"type": r.aggregate_type, "id": str(r.aggregate_id)},
                "occurred_at": r.created_at.isoformat(),
                "payload": r.payload,
            }
            await js.publish(
                bus.subject_for(str(r.tenant_id), r.event_type),
                json.dumps(envelope).encode(),
                headers={"Nats-Msg-Id": str(r.id) if r.replay_gen == 0 else f"{r.id}:r{r.replay_gen}"},
            )
            done.append((r.tenant_id, r.id))
        if crash_after_publish:
            raise RuntimeError("simulated crash before marking published")
        for tid, eid in done:
            conn.execute(
                text("UPDATE events_outbox SET published_at = now() WHERE tenant_id = :t AND id = :i"),
                {"t": tid, "i": eid},
            )
    return len(done)


def replay(engine: Engine, since: str, tenant_id: str | None = None) -> int:
    """Mark events created since `since` (ISO timestamp) as unpublished so the relay republishes them.

    Recovery path for expired/lost bus messages. Each replay bumps replay_gen, so the republish uses
    a NEW Nats-Msg-Id (bypasses bus dedupe even inside the duplicate window) while the envelope keeps
    the original event id: consumers stay exactly-once through the processed_events ledger.
    """
    with engine.begin() as conn:
        return conn.execute(
            text(
                "UPDATE events_outbox SET published_at = NULL, replay_gen = replay_gen + 1 "
                "WHERE created_at >= CAST(:s AS timestamptz) AND (CAST(:t AS uuid) IS NULL OR tenant_id = CAST(:t AS uuid))"
            ),
            {"s": since, "t": tenant_id},
        ).rowcount


async def run() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO)
    engine = make_engine(os.environ["WORKER_DATABASE_URL"])
    nc, js = await bus.connect(os.environ["NATS_URL"])
    await bus.ensure_streams(js)
    interval = float(os.environ.get("RELAY_INTERVAL_S", "1"))
    while True:
        try:
            n = await relay_once(engine, js)
            if n:
                log.info("relayed %d events", n)
        except Exception:
            log.exception("relay iteration failed; retrying")
        await asyncio.sleep(interval)
    await nc.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "replay":
        print(replay(make_engine(os.environ["WORKER_DATABASE_URL"]), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
    else:
        asyncio.run(run())
