"""Per-agent intake limit: a token bucket per (tenant, Edge) on the Edge data-intake routes. 429 `edge_rate_limited` + Retry-After; the budget is the agent's own; nothing is spent before authentication."""
import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.api import deps
from app.core import settings as settings_mod
from app.core.ratelimit import MAX_KEYS, TokenBucketLimiter
from tests.conftest import _now, agent, snap

CAPABLE = {"X-Edge-Backoff": "retry-after"}   # what a current Edge sends: "I treat 429 as wait-and-keep"


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


def test_the_table_is_bounded_and_an_active_bucket_is_never_evicted_for_a_free_burst():
    c = Clock()
    lim = TokenBucketLimiter(burst=2, per_minute=60, clock=c)
    assert [lim.take("victim"), lim.take("victim")] == [0.0, 0.0] and lim.take("victim") > 0      # the victim spent its burst
    for i in range(MAX_KEYS + 50):
        lim.take(f"k{i}")
    assert len(lim._buckets) <= MAX_KEYS
    assert lim.take("victim") > 0                                                                  # still empty: filling the table never gave it a fresh bucket
    assert lim.take("brand-new") > 0                                                               # a NEW identity waits while the table is full of active ones...
    c.t += 10                                                                                      # ...and gets in once the idle ones are full again and dropped
    assert lim.take("brand-new") == 0.0 and len(lim._buckets) <= MAX_KEYS
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
    a1, a2, b1 = ({**agent(client, inv, k), **CAPABLE} for k in ("a1", "a2", "b1"))
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
    a1 = {**agent(client, inv, "a1"), **CAPABLE}
    assert client.post("/v1/edge/olt-snapshots", headers=a1, json=snap(inv, "a1", name="OLT-RL-4")).status_code == 202   # the whole burst was still there


def test_the_default_leaves_a_healthy_edge_far_from_the_limit(client, seed, inv, monkeypatch):
    monkeypatch.delenv("EDGE_INGEST_BURST", raising=False)
    monkeypatch.delenv("EDGE_INGEST_PER_MINUTE", raising=False)
    settings_mod.get_settings.cache_clear()
    deps._INGEST_LIMITERS.clear()
    try:
        s = settings_mod.get_settings()
        assert (s.edge_ingest_burst, s.edge_ingest_per_minute) == (30, 120)
        a2 = {**agent(client, inv, "a2"), **CAPABLE}
        assert all(client.post("/v1/edge/olt-snapshots", headers=a2, json=snap(inv, "a2", name="OLT-RL-5")).status_code == 202 for _ in range(25))
    finally:
        monkeypatch.undo()
        settings_mod.get_settings.cache_clear()
        deps._INGEST_LIMITERS.clear()


def _burst(client, headers, inv, key, name, n=6):
    return [client.post("/v1/edge/olt-snapshots", headers=headers, json=snap(inv, key, name=name)).status_code for _ in range(n)]


def test_an_edge_that_does_not_announce_it_understands_429_is_never_limited_by_default(client, seed, inv, tight):
    """Version skew: an older Edge counts a 429 as a failed attempt and would dead-letter good data after 20 of them, so in the default mode it is simply not limited."""
    assert settings_mod.get_settings().edge_ingest_limit == "capable"
    assert set(_burst(client, agent(client, inv, "a1"), inv, "a1", "OLT-RL-6", n=8)) == {202}          # budget is 3: no header, no limit
    assert _burst(client, {**agent(client, inv, "a2"), **CAPABLE}, inv, "a2", "OLT-RL-7")[3:] == [429, 429, 429]


def test_mode_all_limits_every_agent_and_mode_off_limits_none(client, seed, inv, tight, monkeypatch):
    for mode, expect_429 in (("all", True), ("off", False)):
        monkeypatch.setenv("EDGE_INGEST_LIMIT", mode)
        settings_mod.get_settings.cache_clear()
        deps._INGEST_LIMITERS.clear()
        codes = _burst(client, agent(client, inv, "b1"), inv, "b1", "OLT-RL-8")                          # no capability header at all
        assert (429 in codes) is expect_429, (mode, codes)
        if mode == "all":
            assert codes[:3] == [202, 202, 202] and codes[3:] == [429, 429, 429]
    monkeypatch.setenv("EDGE_INGEST_LIMIT", "nope")
    settings_mod.get_settings.cache_clear()
    with pytest.raises(ValidationError):
        settings_mod.get_settings()                                                                       # a typo in the mode fails closed at startup, not silently open
    monkeypatch.delenv("EDGE_INGEST_LIMIT")
    settings_mod.get_settings.cache_clear()
