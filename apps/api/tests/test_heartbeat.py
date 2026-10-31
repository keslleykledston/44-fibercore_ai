import os
import time

from app.core import heartbeat


def test_beat_is_a_noop_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv("HEARTBEAT_FILE", raising=False)
    heartbeat.beat()  # não levanta, não cria nada


def test_beat_touches_and_age_reads(monkeypatch, tmp_path):
    f = tmp_path / "hb"
    monkeypatch.setenv("HEARTBEAT_FILE", str(f))
    heartbeat.beat()
    assert f.exists() and heartbeat.age_s(str(f)) < 5
    assert heartbeat.main(["x", str(f), "60"]) == 0
    old = time.time() - 120
    os.utime(f, (old, old))
    assert heartbeat.main(["x", str(f), "60"]) == 1  # velho demais => unhealthy


def test_missing_file_is_infinite_age_and_unhealthy(tmp_path):
    assert heartbeat.age_s(str(tmp_path / "nope")) == float("inf")
    assert heartbeat.main(["x", str(tmp_path / "nope"), "60"]) == 1


def test_beat_never_raises_on_unwritable_path(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_FILE", "/proc/forbidden/hb")
    heartbeat.beat()


def test_consumer_counts_handler_failures_and_db_probe(monkeypatch):
    import asyncio

    from app.events import consumer

    class Meta:
        num_delivered = 1

    class Msg:
        data = b"not json"
        subject = "x.y.z"
        metadata = Meta()

        async def nak(self, delay=0):
            pass

    class Sub:
        async def fetch(self, n, timeout):
            return [Msg()]

    stats: dict = {}
    n = asyncio.run(consumer.consume_batch(Sub(), None, None, "c", lambda *a: None, stats=stats))
    assert n == 1 and stats["failed"] == 1  # falha de handler é visível ao laço (sem batimento)

    class Boom:
        def connect(self):
            raise RuntimeError("db down")

    assert consumer._db_ok(Boom()) is False
