"""Fleet Manager (ADR-0041, PR2 part B): the connection test = the closed read `olt.connection` through the existing olt_query engine, under the budget the owner approved
(ONE per OLT every 15 minutes, FOUR per hour), cache-first. Nothing here reaches equipment."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text

from app.core import olt_cache, olt_query
from tests.conftest import hdr
from tests.test_olt_query import olt, on  # noqa: F401  (fixtures: an OLT read by edge a1, and the olt_query flag + Edge channel)

FEATURE = "fleet_manager"
IDENT = {"product": "MA5800-X7", "version": "R018", "patch": "SPC100", "uptime_seconds": 1234}


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'fleet_manager'"))
        c.execute(text("DELETE FROM olt_connection_tests"))


def _flag(migrated, tenant, value=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,:v) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = :v"), {"t": tenant, "f": FEATURE, "v": value})


def _test(client, h, olt_id, key=None):
    return client.post(f"/v1/fleet/olts/{olt_id}/connection-test", headers={**h, **({"Idempotency-Key": key} if key else {})})


def _backdate(migrated, olt_id, minutes_list):
    """Insert 'submitted' rows as if the tests had been asked this many minutes ago (a row cannot be edited by the application; the owner connection here stands in for time passing)."""
    with migrated.begin() as c:
        tenant = c.execute(text("SELECT tenant_id FROM olts WHERE id = :o"), {"o": olt_id}).scalar()
        for m in minutes_list:
            c.execute(text("INSERT INTO olt_connection_tests (tenant_id, olt_id, job_id, outcome, requested_at) VALUES (:t,:o,gen_random_uuid(),'submitted', now() - make_interval(mins => :m))"),
                      {"t": tenant, "o": olt_id, "m": m})


def _store(seed, olt_id, data, asked, source="job"):
    from app.core.db import get_engine, scoped_connection
    with scoped_connection(get_engine(), tenant_id=seed["A"]) as c:
        epoch = c.execute(text("SELECT owner_epoch FROM olts WHERE id = :i"), {"i": olt_id}).scalar()
        olt_cache.store_latest(c, seed["A"], UUID(str(olt_id)), "olt.connection", "", data, epoch, asked, source=source)


def test_flag_and_roles(client, seed, inv, olt, on, migrated):  # noqa: F811
    h, hn1 = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")
    r = _test(client, h, olt)
    assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
    _flag(migrated, seed["A"])
    assert _test(client, hn1, olt).status_code == 403                                  # noc_n1 holds no fleet:test
    assert client.get(f"/v1/fleet/olts/{olt}/connection-tests", headers=hn1).status_code == 403
    assert _test(client, h, "00000000-0000-0000-0000-000000000001").status_code == 404


def test_the_first_test_creates_the_read_job_and_the_second_waits_for_the_gap(client, seed, inv, olt, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    r = _test(client, h, olt)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["outcome"] == "submitted" and b["job_status"] in ("APPROVED", "SUBMITTED", "PENDING_APPROVAL") and b["budget"]["used_last_hour"] == 1
    with migrated.begin() as c:
        job = c.execute(text("SELECT operation, params::text AS p, status FROM jobs WHERE operation = 'olt_query' ORDER BY created_at DESC LIMIT 1")).first()
    assert job.operation == "olt_query" and "olt.connection" in job.p                # the existing engine, the closed read: no channel of its own
    again = _test(client, h, olt)
    assert again.status_code == 429 and again.json()["detail"] == "test_budget"
    assert 600 <= int(again.headers["Retry-After"]) <= 901                            # about 15 minutes
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query' AND params::text LIKE '%olt.connection%'")).scalar() == 1   # the refusal created nothing
    hist = client.get(f"/v1/fleet/olts/{olt}/connection-tests", headers=h).json()
    assert [x["outcome"] for x in hist["items"]] == ["submitted"] and hist["items"][0]["job_status"] is not None
    assert hist["budget"]["wait_seconds"] > 0 and hist["latest"] is None


def test_a_retry_with_the_same_key_returns_the_job_it_created_not_a_budget_refusal(client, seed, inv, olt, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    first = _test(client, h, olt, key="fleet-retry-key-0001")
    assert first.status_code == 200 and first.json()["outcome"] == "submitted"
    retry = _test(client, h, olt, key="fleet-retry-key-0001")                         # timeout/retry inside the 15 minutes: recovers the accepted request
    assert retry.status_code == 200 and retry.json()["outcome"] == "existing"
    other = _test(client, h, olt, key="fleet-other-key-0002")                         # a NEW key is a new test and the budget still refuses it
    assert other.status_code == 429 and other.json()["detail"] == "test_budget"
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query' AND params::text LIKE '%olt.connection%'")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM olt_connection_tests WHERE outcome = 'submitted'")).scalar() == 1


def test_the_generic_job_and_query_routes_refuse_the_connection_test(client, seed, inv, olt, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    r = client.post("/v1/jobs/preview", headers={**h, "Idempotency-Key": "generic-route-0001"}, json={"operation": "olt_query", "target_id": str(olt), "params": {"query_id": "olt.connection"}})
    assert r.status_code == 409 and r.json()["detail"] == "use_fleet_api"
    r = client.post(f"/v1/olts/{olt}/queries/olt.connection", headers={**h, "Idempotency-Key": "generic-route-0002"}, json={"params": {}, "refresh": True})
    assert r.status_code == 409 and r.json()["detail"] == "use_fleet_api"
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query' AND params::text LIKE '%olt.connection%'")).scalar() == 0


def test_the_budget_is_one_per_fifteen_minutes_and_four_per_hour(client, seed, inv, olt, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    _backdate(migrated, olt, [16])                                                    # one 16 minutes ago: the gap is over
    assert _test(client, h, olt).status_code == 200
    with migrated.begin() as c:
        c.execute(text("DELETE FROM olt_connection_tests"))
        c.execute(text("DELETE FROM jobs WHERE operation = 'olt_query'"))
    _backdate(migrated, olt, [59, 44, 29, 16])                                        # four inside the last hour, each 15+ minutes apart
    over = _test(client, h, olt)
    assert over.status_code == 429 and over.json()["detail"] == "test_budget"
    assert 0 < int(over.headers["Retry-After"]) <= 70                                 # the oldest leaves the hour in about a minute


def test_a_fresh_identity_answers_from_the_cache_without_spending_the_budget(client, seed, inv, olt, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    _store(seed, olt, IDENT, datetime.now(UTC) - timedelta(minutes=2))
    r = _test(client, h, olt)
    assert r.status_code == 200 and r.json()["outcome"] == "cached"
    idt = r.json()["identity"]
    assert (idt["model"], idt["firmware"], idt["vendor"], idt["matches_collected"]) == ("MA5800-X7", "R018", "huawei", True)   # equals what the Edge's collection already reported
    for _ in range(3):
        assert _test(client, h, olt).json()["outcome"] == "cached"                    # a cached answer never touches the equipment and never spends the budget
    hist = client.get(f"/v1/fleet/olts/{olt}/connection-tests", headers=h).json()
    assert hist["budget"]["used_last_hour"] == 0 and hist["latest"]["identity"]["model"] == "MA5800-X7"
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE operation = 'olt_query' AND params::text LIKE '%olt.connection%'")).scalar() == 0


def test_a_divergent_identity_is_reported_not_hidden(client, seed, inv, olt, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    _store(seed, olt, {**IDENT, "product": "MA5608T", "version": "MA5600V800R015C00"}, datetime.now(UTC))
    idt = _test(client, h, olt).json()["identity"]
    assert idt["matches_collected"] is False and idt["model"] == "MA5608T"            # the OLT says one thing, the collection another: the screen must show both


def test_an_old_mock_or_malformed_identity_is_never_used_as_a_cached_answer(client, seed, inv, olt, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    _store(seed, olt, IDENT, datetime.now(UTC))
    with migrated.begin() as c:                                                       # past the TTL (the age counts from when the Cloud received it): a job is made instead
        c.execute(text("UPDATE olt_query_latest SET observed_at = now() - interval '3 hours' WHERE query_id = 'olt.connection'"))
    assert _test(client, h, olt).json()["outcome"] == "submitted"
    with migrated.begin() as c:
        c.execute(text("DELETE FROM olt_connection_tests")); c.execute(text("DELETE FROM jobs WHERE operation = 'olt_query'"))
    _store(seed, olt, IDENT, datetime.now(UTC), source="mock")
    assert _test(client, h, olt).json()["outcome"] == "submitted"
    with migrated.begin() as c:
        c.execute(text("DELETE FROM olt_connection_tests")); c.execute(text("DELETE FROM jobs WHERE operation = 'olt_query'"))
    _store(seed, olt, {**IDENT, "password": "x"}, datetime.now(UTC) + timedelta(seconds=1))
    assert _test(client, h, olt).json()["outcome"] == "submitted"                     # a shape outside the closed one is not an answer


def test_the_rollout_and_the_tenant_decide(client, seed, inv, olt, on, migrated, monkeypatch):  # noqa: F811
    _flag(migrated, seed["A"]); _flag(migrated, seed["B"])
    ha, hb = hdr(client, "alice", seed, "A"), hdr(client, "bob", seed, "B")
    assert _test(client, hb, olt).status_code == 404                                  # another tenant's OLT is simply not found
    assert client.get(f"/v1/fleet/olts/{olt}/connection-tests", headers=hb).status_code == 404
    monkeypatch.setattr(olt_query, "ROLLOUT", frozenset(olt_query.ROLLOUT - {"olt.connection"}))
    r = _test(client, ha, olt)
    assert r.status_code == 409                                                       # withdrawn from the rollout: the same gate as any olt_query
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM olt_connection_tests")).scalar() == 0
