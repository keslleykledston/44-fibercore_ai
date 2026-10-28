"""Outbox + JetStream: relay crash/restart, duplicate publish and consumer redelivery.

Needs TEST_NATS_URL (JetStream-enabled NATS), e.g. nats://127.0.0.1:54222
"""
import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.db import make_engine, scoped_connection
from app.events import bus, consumer, outbox
from app.workers.relay import relay_once

NATS_URL = os.environ.get("TEST_NATS_URL")
pytestmark = pytest.mark.skipif(not NATS_URL, reason="TEST_NATS_URL not set")


def run(coro):
    return asyncio.run(coro)


async def fresh_js(dup: float = 3600.0):
    nc, js = await bus.connect(NATS_URL)
    for name in (bus.STREAM, bus.DLQ_STREAM):
        try:
            await js.delete_stream(name)
        except Exception:  # noqa: S110
            pass
    await bus.ensure_streams(js, duplicate_window_s=dup)
    return nc, js


async def stream_count(js) -> int:
    return (await js.stream_info(bus.STREAM)).state.messages


def new_event(app_engine, tenant, etype="olt.test"):
    with scoped_connection(app_engine, tenant_id=tenant) as c:
        return outbox.enqueue(c, tenant_id=tenant, aggregate_type="olt", aggregate_id=uuid4(),
                              event_type=etype, payload={"k": "v"})


@pytest.fixture
def engines(seed, app_url, worker_url, migrated):
    with migrated.begin() as c:
        c.execute(text("TRUNCATE events_outbox, processed_events"))
    return make_engine(app_url), make_engine(worker_url)


def test_worker_role_is_least_privilege(engines, seed):
    app_e, worker_e = engines
    new_event(app_e, seed["A"])
    with worker_e.connect() as c:
        assert c.execute(text("SELECT count(*) FROM events_outbox")).scalar() == 1  # sees all tenants
    for stmt in ("DELETE FROM events_outbox", "UPDATE events_outbox SET payload='{}'::jsonb",
                 "SELECT count(*) FROM audit_log", "INSERT INTO tenants(name) VALUES ('x')"):
        with pytest.raises(Exception):  # noqa: B017, PT011
            with worker_e.begin() as c:
                c.execute(text(stmt))


def test_relay_publishes_and_marks(engines, seed):
    app_e, worker_e = engines
    eid = new_event(app_e, seed["A"])

    async def go():
        nc, js = await fresh_js()
        assert await relay_once(worker_e, js) == 1
        assert await relay_once(worker_e, js) == 0
        n = await stream_count(js)
        await nc.close()
        return n

    assert run(go()) == 1
    with worker_e.connect() as c:
        assert c.execute(text("SELECT published_at IS NOT NULL FROM events_outbox WHERE id=:i"), {"i": eid}).scalar()


def test_relay_crash_then_restart_no_duplicate_on_bus(engines, seed):
    app_e, worker_e = engines
    new_event(app_e, seed["A"])

    async def go():
        nc, js = await fresh_js()
        with pytest.raises(RuntimeError):
            await relay_once(worker_e, js, crash_after_publish=True)  # published, not marked
        assert await stream_count(js) == 1
        assert await relay_once(worker_e, js) == 1  # restart republishes...
        n = await stream_count(js)  # ...but JetStream dedupes by Nats-Msg-Id
        await nc.close()
        return n

    assert run(go()) == 1


def test_consumer_idempotent_across_redelivery_and_restart(engines, seed):
    app_e, worker_e = engines
    eid = new_event(app_e, seed["A"])
    calls = []

    def handler(conn, env):
        calls.append(env["id"])
        consumer.audit_handler(conn, env)

    async def go():
        nc, js = await fresh_js()
        await relay_once(worker_e, js)
        sub = await consumer.ensure_consumer(js, "t-consumer")
        assert await consumer.consume_batch(sub, js, app_e, "t-consumer", handler) == 1
        # same event re-published with a different Msg-Id (bypasses bus dedupe) => ledger must catch it
        import json
        env = {"id": str(eid), "tenant_id": str(seed["A"]), "type": "olt.test", "schema_version": "1",
               "aggregate": {"type": "olt", "id": str(uuid4())}, "occurred_at": "x", "payload": {}}
        await js.publish(bus.subject_for(str(seed["A"]), "olt.test"), json.dumps(env).encode(),
                         headers={"Nats-Msg-Id": str(uuid4())})
        assert await consumer.consume_batch(sub, js, app_e, "t-consumer", handler) == 1
        # "restart": new subscription object on the same durable consumer; nothing left to process
        await nc.close()
        nc2, js2 = await bus.connect(NATS_URL)
        sub2 = await consumer.ensure_consumer(js2, "t-consumer")
        assert await consumer.consume_batch(sub2, js2, app_e, "t-consumer", handler, timeout=0.5) == 0
        await nc2.close()

    run(go())
    assert calls == [str(eid)]  # handler effect applied exactly once
    with scoped_connection(app_e, tenant_id=seed["A"]) as c:
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action='event.consumed'")).scalar() >= 1


def test_failed_handler_is_redelivered_then_succeeds(engines, seed):
    app_e, worker_e = engines
    new_event(app_e, seed["A"])
    state = {"n": 0}

    def flaky(conn, env):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom")
        consumer.audit_handler(conn, env)

    async def go():
        nc, js = await fresh_js()
        await relay_once(worker_e, js)
        sub = await consumer.ensure_consumer(js, "t-flaky")
        await consumer.consume_batch(sub, js, app_e, "t-flaky", flaky)  # fails -> NAK(2s), ledger rolled back
        await asyncio.sleep(2.5)
        assert await consumer.consume_batch(sub, js, app_e, "t-flaky", flaky, timeout=3) == 1
        await nc.close()

    run(go())
    assert state["n"] == 2


def test_tenant_subject_mismatch_not_processed(engines, seed):
    app_e, _ = engines

    async def go():
        import json
        nc, js = await fresh_js()
        env = {"id": str(uuid4()), "tenant_id": str(seed["B"]), "type": "x", "schema_version": "1",
               "aggregate": {"type": "a", "id": str(uuid4())}, "occurred_at": "x", "payload": {}}
        await js.publish(bus.subject_for(str(seed["A"]), "x"), json.dumps(env).encode())
        sub = await consumer.ensure_consumer(js, "t-mismatch")
        called = []
        await consumer.consume_batch(sub, js, app_e, "t-mismatch", lambda c, e: called.append(1))
        await nc.close()
        return called

    assert run(go()) == []


def test_replay_republishes_after_bus_loss(engines, seed):
    from app.workers.relay import replay
    app_e, worker_e = engines
    new_event(app_e, seed["A"])

    async def go():
        nc, js = await fresh_js()
        await relay_once(worker_e, js)
        await js.purge_stream(bus.STREAM)  # simulate expired/lost messages
        assert await stream_count(js) == 0
        assert replay(worker_e, "2000-01-01T00:00:00Z") == 1
        assert replay(worker_e, "2000-01-01T00:00:00Z", str(seed["B"])) == 0  # tenant filter
        await relay_once(worker_e, js)
        n = await stream_count(js)
        await nc.close()
        return n

    assert run(go()) == 1


def test_replay_does_not_double_apply_when_message_still_on_bus(engines, seed):
    from app.workers.relay import replay
    app_e, worker_e = engines
    new_event(app_e, seed["A"])
    calls = []

    async def go():
        nc, js = await fresh_js()
        await relay_once(worker_e, js)
        replay(worker_e, "2000-01-01T00:00:00Z")
        await relay_once(worker_e, js)  # now 2 bus messages, same envelope id
        assert await stream_count(js) == 2
        sub = await consumer.ensure_consumer(js, "t-replay")
        await consumer.consume_batch(sub, js, app_e, "t-replay", lambda c, e: calls.append(e["id"]))
        await nc.close()

    run(go())
    assert len(calls) == 1


def test_ensure_streams_idempotent_and_concurrent():
    async def go():
        nc, js = await fresh_js()
        await bus.ensure_streams(js)  # second call, same config
        await asyncio.gather(*(bus.ensure_streams(js) for _ in range(4)))  # concurrent starts
        await bus.ensure_streams(js, duplicate_window_s=120.0)  # changed config => update, not crash
        info = await js.stream_info(bus.STREAM)
        await nc.close()
        return info.config.duplicate_window

    assert run(go()) == 120.0
