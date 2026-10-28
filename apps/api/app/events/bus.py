"""JetStream helpers. Subjects are per tenant: fibercore.events.<tenant_id>.<event_type>.

Publishing sets Nats-Msg-Id = outbox event id => JetStream de-duplicates relay retries
(within the stream duplicate window). Consumers must still be idempotent (see consumer.py).
"""
from __future__ import annotations

import nats
from nats.js.api import RetentionPolicy, StreamConfig

STREAM = "FIBERCORE_EVENTS"
SUBJECT_ROOT = "fibercore.events"
DLQ_STREAM = "FIBERCORE_DLQ"
DLQ_ROOT = "fibercore.dlq"


def subject_for(tenant_id: str, event_type: str) -> str:
    if not all(c.isalnum() or c in "-_." for c in event_type) or ".." in event_type or not event_type:
        raise ValueError("invalid event_type")
    return f"{SUBJECT_ROOT}.{tenant_id}.{event_type}"


async def connect(url: str):
    nc = await nats.connect(url, connect_timeout=3, max_reconnect_attempts=3)
    return nc, nc.jetstream()


async def ensure_streams(js, *, duplicate_window_s: float = 3600.0) -> None:
    await js.add_stream(
        StreamConfig(
            name=STREAM,
            subjects=[f"{SUBJECT_ROOT}.>"],
            retention=RetentionPolicy.LIMITS,
            duplicate_window=duplicate_window_s,
            max_age=7 * 24 * 3600,
        )
    )
    await js.add_stream(StreamConfig(name=DLQ_STREAM, subjects=[f"{DLQ_ROOT}.>"], max_age=30 * 24 * 3600))
