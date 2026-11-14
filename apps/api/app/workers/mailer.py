"""Mailer: delivers what `email_queue` holds (ADR-0048). Runs as role `fibercore_worker`, which has no grant on the table: it only calls `app_mail_claim`, `app_mail_finish` and
`app_mail_sweep` (migration 0056). Without SMTP configured (`app.core.mail.enabled`) it only keeps its heartbeat: nothing is claimed, so nothing is lost or half-sent.

What it logs: COUNTS and the exception CLASS. Never an address, a subject, a body or a link.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core import mail
from app.core.db import make_engine
from app.core.heartbeat import beat
from app.core.settings import Settings, get_settings

log = logging.getLogger("mailer")
BATCH = 20


def run_once(engine: Engine, settings: Settings, deliver: Callable[[Settings, str, str, str], None] = mail.deliver) -> dict[str, int]:
    out = {"claimed": 0, "sent": 0, "failed": 0, "expired": 0, "purged": 0}
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, to_address, subject, body FROM app_mail_claim(:n)"), {"n": BATCH}).all()
    out["claimed"] = len(rows)
    for r in rows:
        err: str | None = None
        try:
            deliver(settings, r.to_address, r.subject, r.body)
        except Exception as exc:   # noqa: BLE001 - any delivery failure is recorded by CLASS and retried (max 5)
            err = type(exc).__name__
        with engine.begin() as conn:
            conn.execute(text("SELECT app_mail_finish(:i, :ok, :e)"), {"i": r.id, "ok": err is None, "e": err})
        out["sent" if err is None else "failed"] += 1
    with engine.begin() as conn:
        s = conn.execute(text("SELECT expired, purged FROM app_mail_sweep()")).one()
    out["expired"], out["purged"] = s.expired, s.purged
    return out


def run() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO)
    engine = make_engine(os.environ["WORKER_DATABASE_URL"])
    interval = float(os.environ.get("MAILER_INTERVAL_S", "10"))
    settings = get_settings()
    if not mail.enabled(settings):
        log.info("e-mail not configured (SMTP_HOST, SMTP_FROM, PUBLIC_BASE_URL): the mailer only keeps its heartbeat")
    while True:
        try:
            if mail.enabled(settings):
                n = run_once(engine, settings)
                if any(n.values()):
                    log.info("mail run: %s", n)
            beat()
        except Exception:
            log.exception("mail iteration failed; retrying")
        time.sleep(interval)


if __name__ == "__main__":
    run()
