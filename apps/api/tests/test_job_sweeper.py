"""Periodic job sweeper (migration 0047): the two reconciliations a silent Edge used to wait for now run on a clock, through ONE function the worker role may execute and nothing else."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import make_engine
from app.workers import sweeper
from tests.conftest import agent
from tests.test_jobs import _pub_b64  # noqa: F401
from tests.test_jobs_bench import _cleanup, _dispatched  # noqa: F401  (autouse cleanup + the dispatched bench write)


@pytest.fixture
def worker(worker_url):
    eng = make_engine(worker_url)
    yield eng
    eng.dispose()


def _status(migrated, jid):
    with migrated.begin() as c:
        return c.execute(text("SELECT status FROM jobs WHERE id = :j"), {"j": jid}).scalar()


def _lock(migrated):
    with migrated.begin() as c:
        return c.execute(text("SELECT write_locked, lock_reason FROM bench_targets")).one()


def test_a_dispatched_job_nobody_reported_expires_and_locks_without_the_edge_polling(client, seed, inv, migrated, worker):
    cpe, h, jid = _dispatched(client, seed, inv, migrated)
    assert sweeper.sweep_once(worker) == {"expired": 0, "unknown": 0, "locked": 0}              # still inside its window: nothing moves
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET expires_at = now() - interval '1 hour' WHERE id = :j"), {"j": jid})
    assert sweeper.sweep_once(worker) == {"expired": 1, "unknown": 0, "locked": 1}              # no GET /v1/edge/jobs/next anywhere
    assert _status(migrated, jid) == "EXPIRED"
    locked, why = _lock(migrated)
    assert locked is True and "never reported" in why
    assert sweeper.sweep_once(worker) == {"expired": 0, "unknown": 0, "locked": 0}              # idempotent


def test_a_bench_write_accepted_and_gone_quiet_becomes_unknown_after_the_stale_window_only(client, seed, inv, migrated, worker):
    cpe, h, jid = _dispatched(client, seed, inv, migrated)
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=agent(client, inv, "a1"), json={"state": "accepted"}).status_code == 204
    assert sweeper.sweep_once(worker)["unknown"] == 0 and _status(migrated, jid) == "ACCEPTED"
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET updated_at = now() - interval '29 minutes' WHERE id = :j"), {"j": jid})
    assert sweeper.sweep_once(worker)["unknown"] == 0                                           # 29 min: not yet
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET updated_at = now() - interval '31 minutes' WHERE id = :j"), {"j": jid})
    assert sweeper.sweep_once(worker) == {"expired": 0, "unknown": 1, "locked": 1}
    assert _status(migrated, jid) == "UNKNOWN"
    locked, why = _lock(migrated)
    assert locked is True and "never finished" in why
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=agent(client, inv, "a1"), json={"state": "succeeded", "postcheck_ok": True}).status_code == 409   # a late report is refused


def test_the_caller_cannot_shorten_the_stale_window_or_widen_what_counts_as_gated(client, seed, inv, migrated, worker):
    cpe, h, jid = _dispatched(client, seed, inv, migrated)
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=agent(client, inv, "a1"), json={"state": "accepted"}).status_code == 204
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET updated_at = now() - interval '5 minutes' WHERE id = :j"), {"j": jid})
    with worker.begin() as c:
        r = c.execute(text("SELECT unknown FROM app_sweep_jobs(CAST(:g AS text[]), 1)"), {"g": ["reboot_cpe"]}).scalar()   # asks for a 1 second window
        assert r == 0                                                                           # the function keeps its own floor of 30 minutes
        r = c.execute(text("SELECT unknown FROM app_sweep_jobs(CAST(:g AS text[]), 3600)"), {"g": []}).scalar()
        assert r == 0                                                                           # an empty gated list moves nothing
    assert _status(migrated, jid) == "ACCEPTED" and _lock(migrated)[0] is False


def test_the_worker_role_reaches_jobs_only_through_the_function_and_no_other_role_may_call_it(client, seed, inv, migrated, worker, app_url):
    cpe, h, jid = _dispatched(client, seed, inv, migrated)
    for stmt in ("SELECT count(*) FROM jobs", "UPDATE jobs SET status = 'UNKNOWN'", "UPDATE bench_targets SET write_locked = false", "SELECT count(*) FROM bench_targets"):
        with pytest.raises(DBAPIError), worker.begin() as c:
            c.execute(text(stmt))
    app = make_engine(app_url)
    with pytest.raises(DBAPIError), app.begin() as c:                                           # the runtime role cannot call it either
        c.execute(text("SELECT * FROM app_sweep_jobs(ARRAY['reboot_cpe'], 1800)"))
    app.dispose()
    assert _status(migrated, jid) == "DISPATCHED"


def test_a_read_job_in_flight_is_never_touched_and_the_other_tenant_is_not_confused(client, seed, inv, migrated, worker):
    cpe, h, jid = _dispatched(client, seed, inv, migrated)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
        edge = c.execute(text("INSERT INTO edges (tenant_id, name) VALUES (:t, 'edge-sweep-b') RETURNING id"), {"t": seed["B"]}).scalar()
        other = c.execute(text(
            "INSERT INTO jobs (tenant_id, edge_id, target_type, target_id, operation, intent_hash, idempotency_key, risk, required_approvals, status, requested_by, nonce, expires_at, updated_at) "
            "VALUES (:t, :e, 'cpe', gen_random_uuid(), 'refresh_cpe', repeat('a', 64), 'sweep-other-tenant-0001', 'R0', 0, 'ACCEPTED', :u, 'n-sweep-b', now() - interval '2 hours', now() - interval '2 hours') "
            "RETURNING id"), {"t": seed["B"], "u": seed["bob"], "e": edge}).scalar()
    try:
        assert sweeper.sweep_once(worker) == {"expired": 0, "unknown": 0, "locked": 0}          # a read is held by no one and is not a gated write
        assert _status(migrated, other) == "ACCEPTED" and _status(migrated, jid) == "DISPATCHED"
        with worker.begin() as c:                                                               # a worker that NAMES the read as gated still moves nothing: the allowlist is inside the function
            assert tuple(c.execute(text("SELECT expired, unknown, locked FROM app_sweep_jobs(CAST(:g AS text[]), 1800)"), {"g": ["refresh_cpe", "olt_query"]}).one()) == (0, 0, 0)
        assert _status(migrated, other) == "ACCEPTED"
    finally:
        with migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
            c.execute(text("DELETE FROM jobs WHERE id = :j"), {"j": other})
            c.execute(text("DELETE FROM edges WHERE name = 'edge-sweep-b'"))


def test_the_gated_list_is_exactly_the_bench_writes_whose_global_gate_is_closed():
    from app.api import jobs
    from app.core import bench
    assert sweeper.gated_ops() == sorted(o for o in bench.BENCH_OPS if jobs._blocked_reason(o)) and sweeper.gated_ops()   # not empty: every bench write is gated today


def test_the_allowlist_inside_the_function_is_the_bench_catalog():
    """The function's own list (it never trusts the caller's) must equal the bench writes the application knows; a new bench write needs a migration that replaces the function."""
    import importlib.util
    from pathlib import Path

    from app.core import bench
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0047_job_sweeper.py"
    spec = importlib.util.spec_from_file_location("mig0047", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.BENCH_WRITE_OPS) == set(bench.BENCH_OPS)
