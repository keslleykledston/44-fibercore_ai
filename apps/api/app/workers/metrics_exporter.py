"""Operational metrics exporter (ADR-0042): what the API process cannot know about itself, as Prometheus text on an INTERNAL port.

Runs as role `fibercore_worker`, whose only way to the data is `app_metrics_snapshot()` (migration 0048): aggregates across tenants, never a row, never an identifier.
It adds two things that are not in the database: the age of the last finished backup (the mtime of `fibercore-prod-*.dump.done`, as the watchdog reads it; the directory is mounted READ-ONLY and
nothing inside the dump is opened) and the free ratio of the filesystems that matter (the container's own root, which is the Docker data filesystem where `pg_data` lives, and the backup directory).

A failed snapshot is `fibercore_exporter_db_up 0` and NO database series at all (never a stale value that looks healthy). The listener is meant for the compose `control` network only (no host port).
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.db import make_engine
from app.core.metrics import render_families

log = logging.getLogger("metrics-exporter")

JOB_STATES = ("DRAFT", "PREVIEWED", "PENDING_APPROVAL", "APPROVED", "DISPATCHED", "ACCEPTED", "DEVICE_PENDING", "VERIFYING", "SUCCEEDED", "FAILED", "EXPIRED", "UNKNOWN", "CANCELLED")
CACHE_S = 10.0  # several scrapers (or a retry) within this window share one database query
Family = tuple[str, str, str, list[tuple[dict[str, str], float]]]


def snapshot(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        return conn.execute(text("SELECT app_metrics_snapshot()")).scalar_one()


def _g(name: str, help_: str, value: float | None, typ: str = "gauge") -> Family:
    return (name, help_, typ, [] if value is None else [({}, float(value))])


def db_families(snap: dict[str, Any]) -> list[Family]:
    jobs = {s: float(snap.get("jobs", {}).get(s, 0)) for s in JOB_STATES}
    for s, n in snap.get("jobs", {}).items():  # a state this build does not know still shows up (never silently dropped)
        jobs.setdefault(s, float(n))
    return [
        ("fibercore_exporter_db_up", "1 if the last database snapshot worked.", "gauge", [({}, 1.0)]),
        _g("fibercore_edges_active", "Edges that are not revoked.", snap["edges_active"]),
        _g("fibercore_edges_never_heartbeat", "Active Edges that never sent a heartbeat.", snap["edges_never_heartbeat"]),
        _g("fibercore_edge_heartbeat_age_seconds_max", "Age of the OLDEST last heartbeat among active Edges that ever sent one (absent when none did).", snap["edge_heartbeat_age_seconds_max"]),
        _g("fibercore_olts_registered", "OLTs whose Edge is not revoked.", snap["olts_registered"]),
        _g("fibercore_olts_never_collected", "Such OLTs with no collection recorded yet.", snap["olts_never_collected"]),
        _g("fibercore_olt_collection_age_seconds_max", "Age of the OLDEST last collection among OLTs that have one (absent when none).", snap["olt_collection_age_seconds_max"]),
        _g("fibercore_outbox_unpublished", "Outbox events not yet published to the bus.", snap["outbox_unpublished"]),
        _g("fibercore_outbox_oldest_unpublished_age_seconds", "Age of the oldest unpublished outbox event (absent when the outbox is drained).", snap["outbox_oldest_unpublished_age_seconds"]),
        ("fibercore_jobs", "Jobs by state: in-flight states always, terminal states over the last 24 h.", "gauge", [({"state": s}, n) for s, n in sorted(jobs.items())]),
        _g("fibercore_jobs_in_flight_oldest_age_seconds", "Seconds since the oldest in-flight job last changed (absent when none is in flight).", snap["jobs_in_flight_oldest_age_seconds"]),
    ]


def backup_families(directory: str, pattern: str, now: float | None = None) -> list[Family]:
    now = time.time() if now is None else now
    done = sorted(glob.glob(os.path.join(directory, pattern))) if directory else []
    mtimes = []
    for p in done:
        try:
            mtimes.append(os.stat(p).st_mtime)
        except OSError:
            continue
    newest = max(mtimes) if mtimes else None
    return [
        _g("fibercore_backup_files_found", "Finished-backup marker files found in the (read-only) backup directory.", float(len(mtimes))),
        _g("fibercore_backup_last_success_timestamp_seconds", "Unix time of the newest finished-backup marker (absent when there is none).", newest),
    ]


def disk_families(paths: dict[str, str]) -> list[Family]:
    samples: list[tuple[dict[str, str], float]] = []
    for label, path in sorted(paths.items()):
        try:
            u = shutil.disk_usage(path)
        except OSError:
            continue
        if u.total:
            samples.append(({"fs": label}, u.free / u.total))
    help_ = "Free space / total space of a filesystem (docker = the container's root, i.e. the Docker data filesystem; backup = the backup directory)."
    return [("fibercore_disk_free_ratio", help_, "gauge", samples)]


class Collector:
    def __init__(self, engine: Engine, backup_dir: str, backup_glob: str, now: Callable[[], float] = time.time, snap: Callable[[Engine], dict[str, Any]] = snapshot) -> None:
        self.engine, self.backup_dir, self.backup_glob, self.now, self.snap = engine, backup_dir, backup_glob, now, snap
        self._lock = threading.Lock()
        self._at = -1e9
        self._db: list[Family] = []

    def _db_part(self) -> list[Family]:
        with self._lock:
            if self.now() - self._at < CACHE_S:
                return self._db
            try:
                self._db = db_families(self.snap(self.engine))
            except Exception:
                log.exception("snapshot failed")  # the traceback may carry the DSN host, never the password (SQLAlchemy masks it)
                self._db = [("fibercore_exporter_db_up", "1 if the last database snapshot worked.", "gauge", [({}, 0.0)])]
            self._at = self.now()
            return self._db

    def render(self) -> str:
        fams = self._db_part() + backup_families(self.backup_dir, self.backup_glob, self.now())
        paths = {"docker": "/"}
        if self.backup_dir:
            paths["backup"] = self.backup_dir
        return render_families(fams + disk_families(paths))


def make_handler(collector: Collector) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                body, ctype, code = b"ok\n", "text/plain", 200
            elif self.path == "/metrics":
                body, ctype, code = collector.render().encode(), "text/plain; version=0.0.4; charset=utf-8", 200
            else:
                body, ctype, code = b"not found\n", "text/plain", 404
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a: Any) -> None:  # no access log: a scrape every 30 s would only be noise
            pass

    return Handler


def run() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO)
    dsn = os.environ["WORKER_DATABASE_URL"]
    engine = make_engine(dsn + ("&" if "?" in dsn else "?") + "connect_timeout=5")  # a database that does not answer must not hang the scrape
    collector = Collector(engine, os.environ.get("BACKUP_DIR", ""), os.environ.get("BACKUP_GLOB", "fibercore-prod-*.dump.done"))
    port = int(os.environ.get("EXPORTER_PORT", "9101"))
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(collector)).serve_forever()  # noqa: S104 - container-internal; the compose file publishes no host port for it


if __name__ == "__main__":
    run()
