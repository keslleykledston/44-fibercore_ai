"""Speed Diagnostics (TR-143) rules that do not depend on HTTP: the throughput arithmetic, the closed shape of what an Edge may report, and the limits
that protect the PON (ADR-0038).

The cloud never receives a URL, an address or a credential for a test node: it knows LOGICAL endpoint ids (`speed_endpoints`), the Edge maps an id to its own
local address. The Edge reports raw counters; this module turns them into Mbps with one pure function, so the number is testable and nobody can store a figure
the counters do not support. No data = no number (never 0). This module reads; it never talks to equipment."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, text

# registry rows that observe the DEVICE and are not a job operation (ADR-0019 informs, never opens a write): what the CPE's TR-143 client does with a 3xx
# answer from an allowed destination. `supported` = it does NOT follow the redirect. Without a row with evidence, redirects are treated as followed.
REDIRECT_PROBE = "speed_test_redirect_probe"
EGRESS_ACL = "speed_test_egress_acl"   # `supported` = the operator confirmed the service WAN's egress ACL allows only the test nodes (checklist item, with evidence)
REGISTRY_ONLY: frozenset[tuple[str, str]] = frozenset({(REDIRECT_PROBE, "tr069"), (EGRESS_ACL, "tr069")})

DIRECTIONS = {"download": "speed_test_download", "upload": "speed_test_upload"}
OPERATION_DIRECTION = {v: k for k, v in DIRECTIONS.items()}

# file sizes the profiles stand for (the Edge holds the same closed list; a size outside it is never requested)
PROFILE_BYTES = {"10mb": 10_000_000, "50mb": 50_000_000, "200mb": 200_000_000}

MIN_RELIABLE_S = 3.0          # a measurement shorter than this is `partial`: TCP has not left slow start
MIN_DURATION_S = 0.001        # the smallest interval the run row can store (duration_ms > 0)
MAX_DURATION_S = 600.0        # a test that "lasted" longer than the Edge's own ceiling is not a measurement
MIN_BYTES_RATIO = 0.95        # a transfer that moved less than this share of the profile is `partial`
MAX_BYTES_RATIO = 1.05        # a counter above the profile by more than this tolerance is not THIS test: inconclusive, never a credible-looking figure

# one test per ONT, one per PON, two per provider (ADR-0038 item 8; the package's limits)
LIMIT_PER_CPE, LIMIT_PER_PON, LIMIT_PER_TENANT = 1, 1, 2
ACTIVE_JOB_STATES = ("PENDING_APPROVAL", "APPROVED", "DISPATCHED", "ACCEPTED", "DEVICE_PENDING", "VERIFYING")

# stable blocker codes (what the screen and the audit say); none carries an address or a name
BLOCKERS = ("feature_disabled", "not_permitted", "not_bench_target", "capability_not_observed", "redirect_unverified", "endpoint_unavailable",
            "endpoint_unhealthy", "pon_unknown", "cpe_busy", "pon_busy", "tenant_busy", "group_mismatch", "operation_not_homologated")

ENDPOINT_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,30}")
TARGET_KINDS = ("CORE", "INTERNET")
STATE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
_INT_FIELDS = ("test_bytes_received", "total_bytes_received", "test_bytes_sent", "total_bytes_sent", "test_file_length")
_ALLOWED = {"direction", "target", "profile", "state", "bom", "eom", "http_status", "polling_ms", *_INT_FIELDS}
_BYTES_MAX = 10**12


@dataclass(frozen=True)
class Computed:
    outcome: str                 # completed | partial | inconclusive | error
    mbps: float | None           # None unless completed/partial
    bytes: int | None
    duration_ms: int | None
    reason: str | None           # stable short code
    basis: str | None            # which counter the figure comes from


def check_counters(direction: str, target: str, profile: str, data) -> dict | None:
    """The Edge's report, accepted only in this exact shape and only for THIS job's direction, endpoint and profile; None = refused as a whole."""
    if not isinstance(data, dict) or not set(data) <= _ALLOWED or {"direction", "target", "profile", "state"} - set(data):
        return None
    if data["direction"] != direction or data["target"] != target or data["profile"] != profile:
        return None
    st = data["state"]
    if not isinstance(st, str) or STATE_RE.fullmatch(st) is None:
        return None
    for k in _INT_FIELDS:
        v = data.get(k)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= _BYTES_MAX):
            return None
    for k, hi in (("http_status", 999), ("polling_ms", 600_000)):
        v = data.get(k)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= hi):
            return None
    for k in ("bom", "eom"):
        v = data.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > 40 or _parse_time(v) is None):
            return None
    return {k: data.get(k) for k in sorted(_ALLOWED)}


def _parse_time(v: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None   # a device time without a zone cannot be compared with anything


def compute(direction: str, profile: str, c: dict) -> Computed:
    """DL = 8 * TestBytesReceived / dt; UL = 8 * (TestBytesSent if the device reports it, else TestFileLength) / dt; dt = EOMTime - BOMTime (device clock,
    only the difference is used). A device that did not complete, or whose counters do not add up, yields NO number."""
    if c["state"] != "Completed":
        return Computed("error", None, None, None, "device_error" if c["state"].startswith("Error_") else "not_completed", None)
    bom, eom = (_parse_time(c[k]) if c.get(k) else None for k in ("bom", "eom"))
    if bom is None or eom is None:
        return Computed("inconclusive", None, None, None, "no_timestamps", None)
    dt = (eom - bom).total_seconds()
    if dt < MIN_DURATION_S or dt > MAX_DURATION_S:   # below a millisecond the stored duration would round to 0 (the table refuses it): not a measurement
        return Computed("inconclusive", None, None, None, "invalid_duration", None)
    if direction == "download":
        basis, n = "test_bytes_received", c.get("test_bytes_received")
    else:
        # the device's own counter wins whenever it reports one, ZERO included (a reported 0 is "nothing was sent", not "not reported")
        basis, n = ("test_bytes_sent", c["test_bytes_sent"]) if c.get("test_bytes_sent") is not None else ("test_file_length", c.get("test_file_length"))
    if not n or n <= 0:
        return Computed("inconclusive", None, None, int(dt * 1000), "no_bytes", basis)
    if n > MAX_BYTES_RATIO * PROFILE_BYTES[profile]:
        return Computed("inconclusive", None, None, int(dt * 1000), "bytes_exceed_profile", basis)
    mbps = round(8 * n / dt / 1e6, 2)
    if mbps <= 0:   # so few bytes that the figure rounds to 0.00: that is "no throughput measured", never a stored 0
        return Computed("inconclusive", None, None, int(dt * 1000), "negligible_rate", basis)
    short = dt < MIN_RELIABLE_S or n < MIN_BYTES_RATIO * PROFILE_BYTES[profile]
    return Computed("partial" if short else "completed", mbps, n, int(dt * 1000), ("too_short" if dt < MIN_RELIABLE_S else "short_transfer") if short else None, basis)


_DETAIL_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")


def safe_detail(detail) -> str | None:
    """What the Edge says about a speed job is kept only as a short code; anything else (a sentence, an address, a URL) becomes `edge_error`."""
    if detail is None:
        return None
    return detail if isinstance(detail, str) and _DETAIL_RE.fullmatch(detail) else "edge_error"


def pon_of(conn: Connection, tenant_id: UUID, cpe_id: UUID) -> UUID | None:
    """The PON of a CPE, only through the ONE confirmed ONU<->CPE link (a suggestion is not a fact); None when it cannot be resolved to exactly one."""
    rows = conn.execute(
        text("SELECT u.pon_id FROM onu_cpe_links l JOIN onus u ON u.tenant_id = l.tenant_id AND u.id = l.onu_id "
             "WHERE l.tenant_id = :t AND l.cpe_id = :c AND l.status = 'confirmed' AND u.pon_id IS NOT NULL"), {"t": tenant_id, "c": cpe_id}).all()
    return rows[0].pon_id if len(rows) == 1 else None


def busy_reason(conn: Connection, tenant_id: UUID, cpe_id: UUID, pon_id: UUID) -> str | None:
    """Slots, counted under a per-tenant lock held to the end of the caller's transaction so two requests cannot both see room that only one has.
    A run counts while its job is live (waiting for approval counts: it holds the slot the approver is about to release)."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"speed-slots|{tenant_id}"})
    n = conn.execute(
        text("SELECT count(*) AS tenant, count(*) FILTER (WHERE r.cpe_id = :c) AS cpe, count(*) FILTER (WHERE r.pon_id = :p) AS pon "
             "FROM speed_test_runs r JOIN jobs j ON j.tenant_id = r.tenant_id AND j.id = r.job_id "
             "WHERE r.tenant_id = :t AND j.status = ANY(:live) AND (j.status NOT IN ('PENDING_APPROVAL', 'APPROVED') OR j.expires_at > now())"),
        {"t": tenant_id, "c": cpe_id, "p": pon_id, "live": list(ACTIVE_JOB_STATES)}).one()
    if n.cpe >= LIMIT_PER_CPE:
        return "cpe_busy"
    if n.pon >= LIMIT_PER_PON:
        return "pon_busy"
    if n.tenant >= LIMIT_PER_TENANT:
        return "tenant_busy"
    return None


def store_result(conn: Connection, tenant_id: UUID, job_id: UUID, direction: str, profile: str, counters: dict) -> Computed:
    """Writes what the pure function computed from the Edge's counters onto the run of this job, once (a repeated report changes nothing)."""
    r = compute(direction, profile, counters)
    conn.execute(
        text("UPDATE speed_test_runs SET outcome = :o, mbps = :m, bytes = :b, duration_ms = :d, reason = :r, basis = :s, completed_at = now() "
             "WHERE tenant_id = :t AND job_id = :j AND outcome IS NULL"),
        {"o": r.outcome, "m": r.mbps, "b": r.bytes, "d": r.duration_ms, "r": r.reason, "s": r.basis, "t": tenant_id, "j": job_id})
    return r


def redirect_verified(conn: Connection, tenant_id: UUID, vendor: str, model: str, firmware: str) -> bool:
    """The destination cannot be swapped by the node: either the CPE's TR-143 client was observed NOT to follow a 3xx (registry row, with evidence), or the
    operator confirmed the egress ACL of the service WAN (registry row, with evidence). Neither row, or without evidence = redirects count as followed."""
    rows = conn.execute(
        text("SELECT 1 FROM device_capabilities WHERE tenant_id = :t AND lower(vendor) = lower(:v) AND lower(model) = lower(:m) AND firmware = :f "
             "AND protocol = 'tr069' AND operation = ANY(:ops) AND status = 'supported' AND evidence_ref IS NOT NULL AND verified_at IS NOT NULL "
             "AND certification IN ('observed', 'certified')"),
        {"t": tenant_id, "v": vendor.strip(), "m": model.strip(), "f": firmware.strip(), "ops": [REDIRECT_PROBE, EGRESS_ACL]}).first()
    return rows is not None
