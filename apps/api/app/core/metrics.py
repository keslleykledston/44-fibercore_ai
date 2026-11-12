"""Prometheus text exposition (ADR-0043), with no dependency: a tiny registry for the API's RED metrics and the renderer the DB exporter shares.

Cardinality and privacy are decided HERE, not by the callers:
* the route label is the route TEMPLATE (`/v1/olts/{olt_id}`), never the raw path; a request that matched no route is `unmatched`;
* the method label is one of a fixed set (`OTHER` otherwise);
* the status label is the numeric code (a few dozen values at most);
* nothing about a tenant, a user, an Edge, an OLT, an address or a secret is ever a label or a value.
The registry is per process. The API runs ONE uvicorn process (Dockerfile); with several workers each would have to be scraped on its own.
"""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterable, Mapping
from typing import Any

METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
UNMATCHED = "unmatched"

# Names the API itself exports (the observability tests check every dashboard/alert expression against these lists).
API_METRICS = (
    "fibercore_http_requests_total",
    "fibercore_http_request_duration_seconds",
    "fibercore_http_requests_in_flight",
    "fibercore_api_build_info",
    "fibercore_api_start_time_seconds",
)
# Names the DB/backup/disk exporter exports (app/workers/metrics_exporter.py).
EXPORTER_METRICS = (
    "fibercore_exporter_db_up",
    "fibercore_edges_active",
    "fibercore_edges_never_heartbeat",
    "fibercore_edge_heartbeat_age_seconds_max",
    "fibercore_olts_registered",
    "fibercore_olts_never_collected",
    "fibercore_olt_collection_age_seconds_max",
    "fibercore_outbox_unpublished",
    "fibercore_outbox_oldest_unpublished_age_seconds",
    "fibercore_jobs",
    "fibercore_jobs_in_flight_oldest_age_seconds",
    "fibercore_backup_dir_readable",
    "fibercore_backup_files_found",
    "fibercore_backup_last_success_timestamp_seconds",
    "fibercore_disk_free_ratio",
)


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(names: tuple[str, ...], values: tuple[str, ...]) -> str:
    return "{" + ",".join(f'{n}="{_esc(v)}"' for n, v in zip(names, values, strict=True)) + "}" if names else ""


def _num(v: float) -> str:
    if v == math.inf:
        return "+Inf"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return repr(float(v)) if isinstance(v, float) else str(v)


def method_label(method: str) -> str:
    return method if method in METHODS else "OTHER"


class Registry:
    """Counters, one histogram and a few gauges, thread-safe (sync endpoints run in a thread pool)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, str], int] = {}
        self._hist: dict[tuple[str, str], list[float]] = {}  # (method, route) -> [bucket counts..., +Inf count, sum]
        self.in_flight = 0

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        m = method_label(method)
        with self._lock:
            k = (m, route, str(status))
            self._requests[k] = self._requests.get(k, 0) + 1
            h = self._hist.setdefault((m, route), [0.0] * (len(DURATION_BUCKETS) + 2))
            for i, ub in enumerate(DURATION_BUCKETS):
                if seconds <= ub:
                    h[i] += 1
            h[len(DURATION_BUCKETS)] += 1  # +Inf == _count
            h[len(DURATION_BUCKETS) + 1] += seconds

    def enter(self) -> None:
        with self._lock:
            self.in_flight += 1

    def leave(self) -> None:
        with self._lock:
            self.in_flight -= 1

    def render(self, *, version: str, started_at: float) -> str:
        with self._lock:
            requests = dict(self._requests)
            hist = {k: list(v) for k, v in self._hist.items()}
            in_flight = self.in_flight
        out: list[str] = []
        out += ["# HELP fibercore_http_requests_total HTTP requests served, by method, route template and status code.", "# TYPE fibercore_http_requests_total counter"]
        for (m, r, s), n in sorted(requests.items()):
            out.append(f"fibercore_http_requests_total{_labels(('method', 'route', 'code'), (m, r, s))} {n}")
        out += ["# HELP fibercore_http_request_duration_seconds HTTP request duration, by method and route template.", "# TYPE fibercore_http_request_duration_seconds histogram"]
        for (m, r), h in sorted(hist.items()):
            for i, ub in enumerate(DURATION_BUCKETS):
                out.append(f"fibercore_http_request_duration_seconds_bucket{_labels(('method', 'route', 'le'), (m, r, _num(ub)))} {_num(h[i])}")
            out.append(f"fibercore_http_request_duration_seconds_bucket{_labels(('method', 'route', 'le'), (m, r, '+Inf'))} {_num(h[len(DURATION_BUCKETS)])}")
            out.append(f"fibercore_http_request_duration_seconds_sum{_labels(('method', 'route'), (m, r))} {_num(h[len(DURATION_BUCKETS) + 1])}")
            out.append(f"fibercore_http_request_duration_seconds_count{_labels(('method', 'route'), (m, r))} {_num(h[len(DURATION_BUCKETS)])}")
        out += ["# HELP fibercore_http_requests_in_flight Requests being served right now.", "# TYPE fibercore_http_requests_in_flight gauge", f"fibercore_http_requests_in_flight {in_flight}"]
        out += ["# HELP fibercore_api_build_info API version (always 1).", "# TYPE fibercore_api_build_info gauge", f"fibercore_api_build_info{_labels(('version',), (version,))} 1"]
        out += ["# HELP fibercore_api_start_time_seconds Unix time the API process started.", "# TYPE fibercore_api_start_time_seconds gauge", f"fibercore_api_start_time_seconds {_num(started_at)}"]
        return "\n".join(out) + "\n"


class MetricsMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware): records method, route template, status and duration; an exception that escapes is counted as a 500 and re-raised."""

    def __init__(self, app: Any, registry: Registry) -> None:
        self.app, self.registry = app, registry

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = {"code": 500}
        started = time.perf_counter()

        async def send_wrapper(message: Mapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
            await send(message)

        self.registry.enter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            self.registry.leave()
            route = scope.get("route")  # set by the router on the shared scope; absent when nothing matched
            template = getattr(route, "path", None) or UNMATCHED
            self.registry.observe(scope.get("method", ""), template, status["code"], time.perf_counter() - started)


def render_families(families: Iterable[tuple[str, str, str, list[tuple[Mapping[str, str], float]]]]) -> str:
    """`(name, help, type, [(labels, value), ...])` -> text exposition. A family without samples still prints HELP/TYPE (so the series is known, just absent)."""
    out: list[str] = []
    for name, help_, typ, samples in families:
        out += [f"# HELP {name} {help_}", f"# TYPE {name} {typ}"]
        for labels, value in samples:
            names = tuple(sorted(labels))
            out.append(f"{name}{_labels(names, tuple(labels[n] for n in names))} {_num(value)}")
    return "\n".join(out) + "\n"
