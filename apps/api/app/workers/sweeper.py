"""Job sweeper: the two reconciliations of a job the Edge went quiet about, on a clock instead of only when that Edge polls.

Runs as role `fibercore_worker`, which has no grant on `jobs` or `bench_targets`: its only way in is the SECURITY DEFINER function `app_sweep_jobs` (migration 0047). The Python
side decides WHICH operations count as gated writes (same rule as `GET /v1/edge/jobs/next`); the function can only expire a dispatched job, mark a gated write UNKNOWN and write-lock its target.
It never releases a lock (`bench-unlock` stays a person's act).
"""
from __future__ import annotations

import logging
import os
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.api import jobs
from app.core import bench
from app.core.db import make_engine
from app.core.heartbeat import beat

log = logging.getLogger("sweeper")


def gated_ops() -> list[str]:
    """The bench writes whose global gate is closed: the ones a silent Edge may have applied."""
    return sorted(o for o in bench.BENCH_OPS if jobs._blocked_reason(o))


def sweep_once(engine: Engine) -> dict[str, int]:
    with engine.begin() as conn:
        r = conn.execute(text("SELECT expired, unknown, locked FROM app_sweep_jobs(CAST(:g AS text[]), :s)"),
                         {"g": gated_ops(), "s": int(jobs.STALE_AFTER.total_seconds())}).one()
    return {"expired": r.expired, "unknown": r.unknown, "locked": r.locked}


def run() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO)
    engine = make_engine(os.environ["WORKER_DATABASE_URL"])
    interval = float(os.environ.get("SWEEPER_INTERVAL_S", "60"))
    while True:
        try:
            n = sweep_once(engine)
            beat()
            if any(n.values()):
                log.info("swept jobs: %s", n)  # counts only: never a target or a parameter
        except Exception:
            log.exception("sweep iteration failed; retrying")
        time.sleep(interval)


if __name__ == "__main__":
    run()
