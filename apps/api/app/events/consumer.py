"""Idempotent JetStream consumer.

Dedup ledger `processed_events(tenant, consumer, event_id)` is written in the SAME DB
transaction as the handler's effect, so redelivery/duplicates never apply twice. Messages
are acked only after commit; handler errors => NAK with delay; after max_deliver the message
goes to the DLQ stream. Runs as role `fibercore_app` with tenant context taken from the
envelope (events originate from our own relay; subject and envelope tenant must agree).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from uuid import UUID

from nats.js.api import AckPolicy, ConsumerConfig
from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

from app.core.db import make_engine, scoped_connection
from app.events import bus

log = logging.getLogger("consumer")
Handler = Callable[[Connection, dict], None]
MAX_DELIVER = 5


def process_envelope(engine: Engine, consumer: str, envelope: dict, handler: Handler) -> bool:
    """Returns True if handler ran, False if it was a duplicate. Raises on handler failure (rolls back)."""
    tenant_id = UUID(envelope["tenant_id"])
    event_id = UUID(envelope["id"])
    with scoped_connection(engine, tenant_id=tenant_id) as conn:
        inserted = conn.execute(
            text(
                "INSERT INTO processed_events (tenant_id, consumer, event_id) VALUES (:t, :c, :e) "
                "ON CONFLICT DO NOTHING RETURNING 1"
            ),
            {"t": tenant_id, "c": consumer, "e": event_id},
        ).first()
        if inserted is None:
            return False
        handler(conn, envelope)
    return True


async def ensure_consumer(js, durable: str, filter_subject: str = f"{bus.SUBJECT_ROOT}.>"):
    return await js.pull_subscribe(
        filter_subject,
        durable=durable,
        stream=bus.STREAM,
        config=ConsumerConfig(
            durable_name=durable, ack_policy=AckPolicy.EXPLICIT, max_deliver=MAX_DELIVER, ack_wait=30,
        ),
    )


async def consume_batch(sub, js, engine: Engine, consumer: str, handler: Handler, *, batch: int = 10, timeout: float = 1.0) -> int:
    """Fetch and process one batch. Returns number of messages handled (including duplicates)."""
    try:
        msgs = await sub.fetch(batch, timeout=timeout)
    except TimeoutError:
        return 0
    for msg in msgs:
        try:
            envelope = json.loads(msg.data)
            parts = msg.subject.split(".")
            if parts[2] != envelope["tenant_id"]:
                raise ValueError("subject/envelope tenant mismatch")
            await asyncio.to_thread(process_envelope, engine, consumer, envelope, handler)
            await msg.ack()
        except Exception:
            delivered = msg.metadata.num_delivered
            log.exception("handler failed (delivery %d)", delivered)
            if delivered >= MAX_DELIVER:
                await js.publish(f"{bus.DLQ_ROOT}.{consumer}", msg.data, headers={"x-original-subject": msg.subject})
                await msg.term()
            else:
                await msg.nak(delay=2)
    return len(msgs)


def audit_handler(conn: Connection, envelope: dict) -> None:
    """Default demo handler: record that the event was consumed (proves tenant-scoped, exactly-once effect)."""
    conn.execute(
        text(
            "INSERT INTO audit_log (tenant_id, action, target_type, target_id, evidence_redacted) "
            "VALUES (:t, 'event.consumed', 'event', :e, CAST(:ev AS jsonb))"
        ),
        {"t": UUID(envelope["tenant_id"]), "e": envelope["id"], "ev": json.dumps({"type": envelope["type"]})},
    )


async def run() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO)
    engine = make_engine(os.environ["DATABASE_URL"])
    nc, js = await bus.connect(os.environ["NATS_URL"])
    await bus.ensure_streams(js)
    sub = await ensure_consumer(js, "audit-projection")
    while True:
        try:
            await consume_batch(sub, js, engine, "audit-projection", audit_handler)
        except Exception:
            log.exception("consume iteration failed")
            await asyncio.sleep(1)
    await nc.close()


if __name__ == "__main__":
    asyncio.run(run())
