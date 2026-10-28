"""JetStream helpers. Subjects are per tenant: fibercore.events.<tenant_id>.<event_type>.

Publishing sets Nats-Msg-Id = outbox event id => JetStream de-duplicates relay retries
(within the stream duplicate window). Consumers must still be idempotent (see consumer.py).
"""
from __future__ import annotations

import os

import nats
from nats.js.api import RetentionPolicy, StreamConfig
from nats.js.errors import BadRequestError, NotFoundError

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


async def ensure_streams(js, *, duplicate_window_s: float = 3600.0, max_age_s: int | None = None, max_bytes: int | None = None) -> None:
    """max_age_s=0 => never expire by age (published_at != consumed; expiry would lose events for
    offline consumers). Bound by max_bytes + alerting; recover older events with relay.replay().
    Limits left as None are PRESERVED on an existing stream (admin-tuned values survive restarts);
    on first creation they come from STREAM_MAX_AGE_S / STREAM_MAX_BYTES env (defaults 0 / unlimited)."""
    await _ensure(
        js,
        StreamConfig(
            name=STREAM,
            subjects=[f"{SUBJECT_ROOT}.>"],
            retention=RetentionPolicy.LIMITS,
            duplicate_window=duplicate_window_s,
            max_age=max_age_s,
            max_bytes=max_bytes,
        ),
        preserve=("max_age", "max_bytes"),
    )
    await _ensure(js, StreamConfig(name=DLQ_STREAM, subjects=[f"{DLQ_ROOT}.>"], max_age=30 * 24 * 3600))


async def _ensure(js, config: StreamConfig, preserve: tuple[str, ...] = ()) -> None:
    """Idempotent create-or-update; safe for concurrent starts (relay + consumer) and restarts.

    Attributes named in `preserve` that are None in `config` keep the live stream's value on update.
    """
    try:
        existing = (await js.stream_info(config.name)).config
    except NotFoundError:
        existing = None
    if existing is None:
        for attr, env, default in (("max_age", "STREAM_MAX_AGE_S", 0), ("max_bytes", "STREAM_MAX_BYTES", -1)):
            if attr in preserve and getattr(config, attr) is None:
                setattr(config, attr, int(os.environ.get(env, default)))
        try:
            await js.add_stream(config)
            return
        except BadRequestError:  # lost the creation race
            existing = (await js.stream_info(config.name)).config
    for attr in preserve:
        if getattr(config, attr) is None:
            setattr(config, attr, getattr(existing, attr))
    await js.update_stream(config)
