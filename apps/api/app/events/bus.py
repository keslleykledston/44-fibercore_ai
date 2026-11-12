"""JetStream helpers. Subjects are per tenant: fibercore.events.<tenant_id>.<event_type>.

Publishing sets Nats-Msg-Id = outbox event id => JetStream de-duplicates relay retries
(within the stream duplicate window). Consumers must still be idempotent (see consumer.py).
"""
from __future__ import annotations

import asyncio
import os
import ssl
from collections.abc import Mapping

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


def connect_options(env: Mapping[str, str] | None = None) -> dict:
    """Extra `nats.connect` options from the environment (ADR-0042). EMPTY when nothing is configured: the plain connection
    (dev / current LAB) is byte-for-byte what it was. Once ANY of these is set it is all-or-nothing and fail-closed: a
    half-configured or unreadable setting raises at startup, it never silently falls back to a plain connection.

      NATS_TLS_CA          CA bundle that signed the server certificate (verifies the server; enables TLS)
      NATS_TLS_CERT/_KEY   this role's client certificate + key (mutual TLS: the cert IS the identity, see infra/nats/nats-server.conf)
      NATS_INBOX_PREFIX    reply-subject prefix, e.g. _INBOX.relay (the ACL only lets a role listen on its own prefix)
    """
    env = os.environ if env is None else env
    ca, cert, key, inbox = (env.get(k, "").strip() for k in ("NATS_TLS_CA", "NATS_TLS_CERT", "NATS_TLS_KEY", "NATS_INBOX_PREFIX"))
    opts: dict = {}
    if bool(cert) != bool(key):
        raise ValueError("NATS_TLS_CERT and NATS_TLS_KEY must be set together")
    if cert and not ca:
        raise ValueError("NATS_TLS_CERT/NATS_TLS_KEY need NATS_TLS_CA (a client identity without verifying the server is refused)")
    if ca:
        try:
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
            if cert:
                ctx.load_cert_chain(certfile=cert, keyfile=key)
        except (OSError, ssl.SSLError) as e:
            raise ValueError(f"NATS TLS configuration unusable: {e}") from e
        opts["tls"] = ctx
    if inbox:
        if not all(c.isalnum() or c in "_.-" for c in inbox) or inbox.endswith((".", ">", "*")) or ".." in inbox:
            raise ValueError("NATS_INBOX_PREFIX must be dot-separated tokens (e.g. _INBOX.relay)")
        opts["inbox_prefix"] = inbox.encode()
    return opts


CONNECT_DEADLINE_S = 20.0   # wall clock for the WHOLE connect: a plain client against a TLS-only server can otherwise wait forever (observed), instead of failing and being restarted


async def connect(url: str):
    nc = await asyncio.wait_for(nats.connect(url, connect_timeout=3, max_reconnect_attempts=3, **connect_options()), CONNECT_DEADLINE_S)
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
