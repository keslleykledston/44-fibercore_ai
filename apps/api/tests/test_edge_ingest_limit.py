"""Per-agent intake limit: a token bucket per (tenant, Edge) on the Edge data-intake routes. 429 `edge_rate_limited` + Retry-After; the budget is the agent's own; nothing is spent before authentication."""
import pytest
from sqlalchemy import text

from app.api import deps
from app.core import settings as settings_mod
from app.core.ratelimit import MAX_KEYS, TokenBucketLimiter
from tests.conftest import _now, agent, snap


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_the_bucket_allows_the_burst_then_refills_at_the_rate():
    c = Clock()
    lim = TokenBucketLimiter(burst=3, per_minute=60, clock=c)           # 1 token per second
    assert [lim.take("a") for _ in range(3)] == [0.0, 0.0, 0.0]
    wait = lim.take("a")
    assert 0.99 < wait <= 1.0 and lim.retry_after(wait) == 1               # empty: one second to the next token
    c.t += 0.5
    assert 0.49 < lim.take("a") <= 0.5                                     # a refused call spends nothing and does not reset the clock
    c.t += 0.5
    assert lim.take("a") == 0.0
    c.t += 100
    assert [lim.take("a") for _ in range(4)] == [0.0, 0.0, 0.0, pytest.approx(1.0, abs=0.01)]   # never above the burst, however long it idled
    assert lim.take("b") == 0.0                                            # another agent has its own bucket


def test_the_table_of_buckets_is_bounded():
    c = Clock()
    lim = TokenBucketLimiter(burst=2, per_minute=60, clock=c)
    for i in range(MAX_KEYS + 50):
        lim.take(f"k{i}")
        c.t += 0.001
    assert len(lim._buckets) <= MAX_KEYS
    with pytest.raises(ValueError):
        TokenBucketLimiter(burst=0, per_minute=10)


@pytest.fixture(autouse=True)
def _clean_up(migrated):
    yield
    with migrated.begin() as c:   # the OLTs these tests ingest must not leak into the suites that assert a tenant has none
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-RL-%'"))


@pytest.fixture
def tight(monkeypatch):
    monkeypatch.setenv("EDGE_INGEST_BURST", "3")
    monkeypatch.setenv("EDGE_INGEST_PER_MINUTE", "60")
    settings_mod.get_settings.cache_clear()
    deps._INGEST_LIMITERS.clear()
    yield
    monkeypatch.undo()
    settings_mod.get_settings.cache_clear()
    deps._INGEST_LIMITERS.clear()


def test_an_agent_over_its_budget_gets_429_with_retry_after_and_others_are_untouched(client, seed, inv, tight):
    a1, a2, b1 = (agent(client, inv, k) for k in ("a1", "a2", "b1"))
    body = snap(inv, "a1", name="OLT-RL-1")
    for _ in range(3):
        assert client.post("/v1/edge/olt-snapshots", headers=a1, json=body).status_code == 202
    r = client.post("/v1/edge/olt-snapshots", headers=a1, json=body)
    assert r.status_code == 429 and r.json()["detail"] == "edge_rate_limited" and 1 <= int(r.headers["Retry-After"]) <= 2
    # the budget covers every intake route of the SAME agent, not one per route
    cpe_body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": []}
    assert client.post("/v1/edge/cpe-snapshots", headers=a1, json=cpe_body).status_code == 429
    assert client.post("/v1/edge/cpe-state", headers=a1, json={"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "states": []}).status_code == 429
    assert client.post("/v1/edge/cpe-config", headers=a1, json={"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "configs": []}).status_code == 429
    assert client.post("/v1/edge/speed-health", headers=a1, json={"endpoints": []}).status_code == 429
    # another Edge of the same tenant, and an Edge of another tenant, keep their own budget
    assert client.post("/v1/edge/olt-snapshots", headers=a2, json=snap(inv, "a2", name="OLT-RL-2")).status_code == 202
    assert client.post("/v1/edge/olt-snapshots", headers=b1, json=snap(inv, "b1", name="OLT-RL-3")).status_code == 202
    # routes that are not data intake are not limited by it (the job poll, the heartbeat and results keep flowing)
    assert client.get("/v1/edge/jobs/next", headers=a1).status_code in (200, 204)


def test_nothing_is_spent_before_authentication_or_authorisation(client, seed, inv, tight):
    for _ in range(6):
        assert client.post("/v1/edge/olt-snapshots", json=snap(inv, "a1", name="OLT-RL-4")).status_code == 401
        assert client.post("/v1/edge/olt-snapshots", headers={"Authorization": "Bearer not-a-token"}, json=snap(inv, "a1", name="OLT-RL-4")).status_code == 401
    a1 = agent(client, inv, "a1")
    assert client.post("/v1/edge/olt-snapshots", headers=a1, json=snap(inv, "a1", name="OLT-RL-4")).status_code == 202   # the whole burst was still there


def test_the_default_leaves_a_healthy_edge_far_from_the_limit(client, seed, inv, monkeypatch):
    monkeypatch.delenv("EDGE_INGEST_BURST", raising=False)
    monkeypatch.delenv("EDGE_INGEST_PER_MINUTE", raising=False)
    settings_mod.get_settings.cache_clear()
    deps._INGEST_LIMITERS.clear()
    try:
        s = settings_mod.get_settings()
        assert (s.edge_ingest_burst, s.edge_ingest_per_minute) == (30, 120)
        a2 = agent(client, inv, "a2")
        assert all(client.post("/v1/edge/olt-snapshots", headers=a2, json=snap(inv, "a2", name="OLT-RL-5")).status_code == 202 for _ in range(25))
    finally:
        monkeypatch.undo()
        settings_mod.get_settings.cache_clear()
        deps._INGEST_LIMITERS.clear()
