"""Cache primeiro das consultas à OLT (ADR-0032 item 4): o resultado tipado de um job alimenta o último valor; um pedido dentro do TTL não cria job; passou do TTL ou
`refresh` pergunta de novo (com cota própria); as mesmas comportas de um job valem para o cache; nada atravessa tenants nem dono anterior."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text

from app.core import olt_cache
from tests.conftest import hdr
from tests.test_olt_query import BOARD, TEMPS, VERSION, _ask, _dispatched, _report, olt, on  # noqa: F401  (fixtures)


def _jobs(migrated, olt_id) -> int:
    with migrated.begin() as c:
        return c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query' AND target_id = :o"), {"o": olt_id}).scalar()


def _succeed(client, seed, inv, olt_id, qid, data):
    h, jid = _dispatched(client, seed, inv, olt_id, qid)
    assert _report(client, inv, jid, state="succeeded", postcheck_ok=True, data=data).status_code == 204
    return h


def _age(migrated, seed, olt_id, qid, seconds):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE olt_query_latest SET observed_at = now() - make_interval(secs => :s) WHERE olt_id = :o AND query_id = :q"), {"s": seconds, "o": olt_id, "q": qid})


def test_params_key_is_canonical():
    assert olt_cache.params_key({}) == "" and olt_cache.params_key({"slot": 3}) == "s=3"
    assert olt_cache.params_key({"slot": 1, "port": 0}) == "s=1,p=0" and olt_cache.params_key({"ont": 9, "port": 0, "slot": 1}) == "s=1,p=0,o=9"


def test_a_result_feeds_the_cache_and_the_next_request_does_not_touch_the_equipment(client, seed, inv, olt, on, migrated):
    h = _succeed(client, seed, inv, olt, "olt.version", VERSION)
    got = client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=h).json()
    assert got["data"] == VERSION and got["stale"] is False and got["source"] == "job" and 0 <= got["age_seconds"] < 60 and got["ttl_seconds"] == 3600
    n = _jobs(migrated, olt)
    again = _ask(client, h, olt, "olt.version").json()
    assert again["outcome"] == "cached" and again["cached"]["data"] == VERSION and _jobs(migrated, olt) == n      # no job, nothing queued for the Edge


def test_a_value_older_than_its_ttl_is_stale_and_the_request_asks_again(client, seed, inv, olt, on, migrated):
    h = _succeed(client, seed, inv, olt, "olt.version", VERSION)
    _age(migrated, seed, olt, "olt.version", 3601)
    got = client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=h).json()
    assert got["stale"] is True and got["age_seconds"] >= 3601
    n = _jobs(migrated, olt)
    assert _ask(client, h, olt, "olt.version").json()["outcome"] == "submitted" and _jobs(migrated, olt) == n + 1


def test_refresh_asks_again_with_its_own_quota(client, seed, inv, olt, on, migrated):
    h = _succeed(client, seed, inv, olt, "olt.version", VERSION)
    for _ in range(olt_cache.REFRESH_PER_HOUR):
        r = client.post(f"/v1/olts/{olt}/queries/olt.version", headers={**h, "Idempotency-Key": f"r-{_}-{UUID(int=_).hex}"}, json={"params": {}, "refresh": True})
        assert r.status_code == 200 and r.json()["outcome"] == "submitted", r.text
    over = client.post(f"/v1/olts/{olt}/queries/olt.version", headers={**h, "Idempotency-Key": "r-over-0000000000"}, json={"params": {}, "refresh": True})
    assert over.status_code == 429 and over.json()["detail"] == "olt_query_refresh_quota"
    assert _ask(client, h, olt, "olt.version").json()["outcome"] == "cached"      # a plain request is still answered from the cache


def test_the_cache_obeys_the_same_gates_as_a_job(client, seed, inv, olt, on, migrated):
    h = _succeed(client, seed, inv, olt, "olt.version", VERSION)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE tenant_id = :t AND feature = 'olt_query'"), {"t": seed["A"]})
    r = _ask(client, h, olt, "olt.version")
    assert r.status_code == 409 and r.json()["detail"] == "olt_query_disabled"      # a cached value is not served once the feature is off
    dave = hdr(client, "dave", seed, "A")
    assert _ask(client, dave, olt, "olt.version").status_code == 403 and client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=dave).status_code == 403


def test_nothing_crosses_tenants_and_unknown_things_are_refused(client, seed, inv, olt, on):
    h = _succeed(client, seed, inv, olt, "olt.version", VERSION)
    bob = hdr(client, "bob", seed, "B")
    assert client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=bob).status_code == 404
    assert client.get(f"/v1/olts/{olt}/queries/olt.board/latest", headers=h).json()["detail"] == "no_cached_value"
    assert client.get(f"/v1/olts/{olt}/queries/olt.nope/latest", headers=h).json()["detail"] == "query_not_enabled"      # unknown or not in the rollout: nothing is offered
    assert client.get(f"/v1/olts/{olt}/queries/olt.version/latest?slot=1", headers=h).json()["detail"] == "fields_do_not_match_scope"
    assert client.get(f"/v1/olts/{olt}/queries/slot.cpu/latest", headers=h).json()["detail"] == "query_not_enabled"


def test_a_result_from_an_edge_that_no_longer_owns_the_olt_does_not_become_the_last_value(client, seed, inv, olt, on, migrated):
    h, jid = _dispatched(client, seed, inv, olt, "olt.version")
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET edge_id = :e WHERE id = :o"), {"e": inv["a2"]["edge"], "o": olt})      # the OLT moved to another Edge meanwhile
    assert _report(client, inv, jid, state="succeeded", postcheck_ok=True, data=VERSION).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "SUCCEEDED"      # the job keeps its own result
    assert client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=h).json()["detail"] == "no_cached_value"
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET edge_id = :e WHERE id = :o"), {"e": inv["a1"]["edge"], "o": olt})


def test_an_older_epoch_or_a_failed_result_never_replaces_the_cache(client, seed, inv, olt, on, migrated):
    h = _succeed(client, seed, inv, olt, "olt.version", VERSION)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE olt_query_latest SET owner_epoch = 3 WHERE olt_id = :o"), {"o": olt})
        assert olt_cache.store_latest(c, seed["A"], UUID(olt), "olt.version", "", {**VERSION, "uptime_seconds": 1}, 2, datetime.now(UTC)) is False      # the previous owner's value
        assert olt_cache.store_latest(c, seed["A"], UUID(olt), "olt.version", "", {**VERSION, "uptime_seconds": 7}, 3, datetime.now(UTC)) is True
    assert client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=h).json()["data"]["uptime_seconds"] == 7
    h2, jid = _dispatched(client, seed, inv, olt, "olt.board")
    _report(client, inv, jid, state="succeeded", postcheck_ok=True, data={"boards": []})      # invalid shape -> FAILED, nothing cached
    assert client.get(f"/v1/olts/{olt}/queries/olt.board/latest", headers=h).json()["detail"] == "no_cached_value"


def test_the_temperature_result_also_feeds_the_series(client, seed, inv, olt, on, migrated):
    _succeed(client, seed, inv, olt, "olt.temperature", TEMPS)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        rows = c.execute(text("SELECT metric, scope_key, value FROM olt_metric_samples WHERE olt_id = :o ORDER BY scope_key"), {"o": olt}).all()
    assert [(r.metric, r.scope_key, float(r.value)) for r in rows] == [("board_temp_c", "s=0", 45.0), ("board_temp_c", "s=2", 43.0)]
    assert BOARD  # (imported to share the vectors of test_olt_query)
    with pytest.raises(Exception, match="row-level security|violates"):
        with migrated.begin() as c:    # no tenant context: the application role would see nothing; the owner cannot insert a foreign row either (FK)
            c.execute(text("INSERT INTO olt_metric_samples (tenant_id, olt_id, metric, scope_key, at, value) VALUES (gen_random_uuid(), :o, 'x_y', '', now(), 1)"), {"o": olt})


def test_the_stored_value_is_hidden_when_the_query_is_withdrawn_or_the_feature_is_off(client, seed, inv, olt, on, migrated, monkeypatch):
    h = _succeed(client, seed, inv, olt, "olt.version", VERSION)
    assert client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=h).status_code == 200
    from app.core import olt_query
    monkeypatch.setattr(olt_query, "ROLLOUT", olt_query.ROLLOUT - {"olt.version"})
    r = client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=h)
    assert (r.status_code, r.json()["detail"]) == (409, "query_not_enabled")
    monkeypatch.undo()
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE tenant_id = :t AND feature = 'olt_query'"), {"t": seed["A"]})
    r = client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=h)
    assert (r.status_code, r.json()["detail"]) == (409, "olt_query_disabled")


def test_concurrent_refreshes_cannot_pass_the_quota_and_a_retry_spends_nothing(client, seed, inv, olt, on, migrated):
    import threading
    h = _succeed(client, seed, inv, olt, "olt.version", VERSION)
    codes = []

    def go(i):
        r = client.post(f"/v1/olts/{olt}/queries/olt.version", headers={**h, "Idempotency-Key": f"conc-{i}-aaaaaaaa"}, json={"params": {}, "refresh": True})
        codes.append(r.status_code)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(7)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200] * olt_cache.REFRESH_PER_HOUR + [429] * (7 - olt_cache.REFRESH_PER_HOUR), codes
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'olt_query.refresh' AND target_id = :o"), {"o": olt}).scalar() == olt_cache.REFRESH_PER_HOUR
    ok = next(i for i, c in enumerate(codes) if c == 200)   # a retry of an accepted refresh (same key) answers 'existing' even though the quota is spent
    done = [i for i in range(7) if client.post(f"/v1/olts/{olt}/queries/olt.version", headers={**h, "Idempotency-Key": f"conc-{i}-aaaaaaaa"}, json={"params": {}, "refresh": True}).json().get("outcome") == "existing"]
    assert len(done) == olt_cache.REFRESH_PER_HOUR and ok is not None


def test_a_late_result_of_an_older_question_does_not_replace_a_newer_value(client, seed, inv, olt, on):
    from tests.conftest import agent
    h = hdr(client, "alice", seed, "A")
    j1 = _ask(client, h, olt, "olt.version").json()["job"]["id"]
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 200
    j2 = client.post(f"/v1/olts/{olt}/queries/olt.version", headers={**h, "Idempotency-Key": "second-aaaaaaaa"}, json={"params": {}, "refresh": True}).json()["job"]["id"]
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 200
    newer = {**VERSION, "uptime_seconds": 200}
    assert _report(client, inv, j2, state="succeeded", postcheck_ok=True, data=newer).status_code == 204
    assert _report(client, inv, j1, state="succeeded", postcheck_ok=True, data=VERSION).status_code == 204      # the OLDER question answers last
    assert client.get(f"/v1/olts/{olt}/queries/olt.version/latest", headers=h).json()["data"] == newer
