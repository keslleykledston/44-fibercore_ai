"""Ping test (TR-143 IPPing) rules that do not depend on HTTP: the closed shape of what an Edge may report, the arithmetic, and the per-CPE reservation
that keeps two diagnostics from fighting over the same device (ADR-0030 amendment line Q1; ADR-0039 items 2 and 3).

The cloud never receives an address or a name for a destination: it knows LOGICAL ids (`probe_targets`), the Edge maps an id to its own local IP literal. The Edge
reports the raw leaves the device gave (counts and min/avg/max times in ms); this module turns them into a result with one pure function, so nobody can store a
figure the leaves do not support. No data = no number (never 0). The device gives no per-reply times: there is NO jitter here, only the spread between the
slowest and the fastest reply (`max - min`), and it is named that way. This module reads; it never talks to equipment."""
from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, text

from app.core import speed

REPETITIONS = 5            # fixed by the Edge (internal/ping); a report whose counts do not add up to it is not THIS test
MAX_RUNS_PER_HOUR = 6      # per CPE, counting every ping request (ADR-0039 item 3): the diagnostic writes to the device
MAX_MS = 86_400_000        # the Edge bounds a leaf at a day; a time above it is not a ping time

TARGET_ID_RE = speed.ENDPOINT_ID_RE
TARGET_KINDS = speed.TARGET_KINDS

_INT_FIELDS = ("success", "failure", "avg_ms", "min_ms", "max_ms")
_ALLOWED = {"target", "state", "polling_ms", *_INT_FIELDS}


@dataclass(frozen=True)
class Computed:
    outcome: str                  # completed | inconclusive | error
    success: int | None
    failure: int | None
    loss_pct: float | None
    avg_ms: int | None
    min_ms: int | None
    max_ms: int | None
    reason: str | None            # stable short code

    @property
    def spread_ms(self) -> int | None:
        return None if self.max_ms is None or self.min_ms is None else self.max_ms - self.min_ms


def check_report(target: str, data) -> dict | None:
    """The Edge's report, accepted only in this exact shape and only for THIS job's destination; None = refused as a whole. A leaf the device did not give is
    absent (not zero)."""
    if not isinstance(data, dict) or not set(data) <= _ALLOWED or {"target", "state"} - set(data) or data["target"] != target:
        return None
    st = data["state"]
    # the Edge sends a report only for a FINISHED diagnostic: Completed, or an Error_ state the device itself reported (a result, like the speed test's). Any
    # other state is not a finished test: the report is refused, the job fails and the target is locked.
    if not isinstance(st, str) or speed.STATE_RE.fullmatch(st) is None or not (st == "Completed" or st.startswith("Error_")):
        return None
    for k in _INT_FIELDS:
        v = data.get(k)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= MAX_MS):
            return None
    v = data.get("polling_ms")
    if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 600_000):
        return None
    return {k: data.get(k) for k in sorted(_ALLOWED)}


def compute(c: dict) -> Computed:
    """A device that reported an error, or whose counts and times do not add up, yields NO figure. With every probe lost the test COMPLETED with 100 % loss and
    no times: that is a result, not an error."""
    if c["state"] != "Completed":
        return Computed("error", None, None, None, None, None, None, "device_error")
    s, f = c.get("success"), c.get("failure")
    if s is None or f is None:
        return Computed("inconclusive", None, None, None, None, None, None, "no_counts")
    if s + f != REPETITIONS:
        return Computed("inconclusive", None, None, None, None, None, None, "counts_mismatch")
    loss = round(100 * f / REPETITIONS, 2)
    if s == 0:
        # nothing came back: any time the device still reports is a leftover of another test, so none is kept
        return Computed("completed", 0, f, loss, None, None, None, None)
    avg, lo, hi = c.get("avg_ms"), c.get("min_ms"), c.get("max_ms")
    if avg is None or lo is None or hi is None:
        return Computed("inconclusive", None, None, None, None, None, None, "no_times")
    if not lo <= avg <= hi:
        return Computed("inconclusive", None, None, None, None, None, None, "times_inconsistent")
    return Computed("completed", s, f, loss, avg, lo, hi, None)


def store_result(conn: Connection, tenant_id: UUID, job_id: UUID, report: dict) -> Computed:
    """Writes what the pure function computed onto the run of this job, once (a repeated report changes nothing)."""
    r = compute(report)
    conn.execute(
        text("UPDATE ping_test_runs SET outcome = :o, success_count = :s, failure_count = :f, loss_pct = :l, avg_ms = :a, min_ms = :mi, max_ms = :ma, "
             "reason = :r, completed_at = now() WHERE tenant_id = :t AND job_id = :j AND outcome IS NULL"),
        {"o": r.outcome, "s": r.success, "f": r.failure, "l": r.loss_pct, "a": r.avg_ms, "mi": r.min_ms, "ma": r.max_ms, "r": r.reason, "t": tenant_id, "j": job_id})
    return r


def store_failure(conn: Connection, tenant_id: UUID, job_id: UUID, reason: str) -> None:
    """A job that ended without a usable report (failed, unknown, refused shape): the run records an `error` with the Edge's short code and no figure."""
    conn.execute(
        text("UPDATE ping_test_runs SET outcome = 'error', reason = :r, completed_at = now() WHERE tenant_id = :t AND job_id = :j AND outcome IS NULL"),
        {"r": reason if re.fullmatch(r"[a-z_]{1,40}", reason or "") else "edge_error", "t": tenant_id, "j": job_id})


def busy_reason(conn: Connection, tenant_id: UUID, cpe_id: UUID) -> str | None:
    """The shared reservation of a CPE (ADR-0039 item 3): one diagnostic at a time on the same device, whichever kind (throughput or ping), counted under the SAME
    per-tenant lock `speed.busy_reason` takes, held to the end of the caller's transaction so two requests cannot both see room that only one has. A run counts
    while its job is live (waiting for approval counts: it holds the slot the approver is about to release). Also the hourly ceiling per CPE."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"speed-slots|{tenant_id}"})
    live = list(speed.ACTIVE_JOB_STATES)
    guard = "j.status = ANY(:live) AND (j.status NOT IN ('PENDING_APPROVAL', 'APPROVED') OR j.expires_at > now())"
    n = conn.execute(
        text("SELECT (SELECT count(*) FROM ping_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id "  # noqa: S608
             f"WHERE r.tenant_id = :t AND r.cpe_id = :c AND {guard}) + "
             "(SELECT count(*) FROM speed_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id "
             f"WHERE r.tenant_id = :t AND r.cpe_id = :c AND {guard}) AS live, "
             "(SELECT count(*) FROM ping_test_runs r WHERE r.tenant_id = :t AND r.cpe_id = :c AND r.created_at > now() - interval '1 hour') AS hour"),
        {"t": tenant_id, "c": cpe_id, "live": live}).one()
    if n.live >= 1:
        return "cpe_busy"
    if n.hour >= MAX_RUNS_PER_HOUR:
        return "rate_limited"
    return None
