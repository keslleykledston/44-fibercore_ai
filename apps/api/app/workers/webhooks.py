"""Webhook dispatcher (ADR-0051 D2). Runs as role `fibercore_worker`, which has no grant on the webhook tables: it only calls `app_webhook_fanout`, `app_webhook_claim`,
`app_webhook_finish` and `app_webhook_sweep` (migration 0061). Without `WEBHOOK_ENCRYPTION_KEY` it only keeps its heartbeat.

What it logs: COUNTS and the failure CLASS. Never a URL, a header, a payload or a secret.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core import webhooks
from app.core.db import make_engine
from app.core.heartbeat import beat
from app.core.settings import Settings, get_settings

log = logging.getLogger("webhooks")
BATCH = 20


def run_once(engine: Engine, settings: Settings, deliver: Callable = webhooks.deliver) -> dict[str, int]:
    out = {"fanned_out": 0, "claimed": 0, "sent": 0, "failed": 0, "expired": 0, "purged": 0}
    with engine.begin() as conn:
        out["fanned_out"] = int(conn.execute(text("SELECT app_webhook_fanout(100)")).scalar_one())
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, url, secret_enc, event_type, payload FROM app_webhook_claim(:n)"), {"n": BATCH}).all()
    out["claimed"] = len(rows)
    for r in rows:
        code, status, ok = None, None, False
        try:
            body, headers = webhooks.build_request(settings, r.secret_enc, r.id, r.event_type, r.payload)
            status = deliver(r.url, body, headers)
            ok = True
        except webhooks.DeliveryError as exc:
            code, status = exc.code, exc.status
        except Exception as exc:   # noqa: BLE001 - any other failure is recorded by CLASS and retried
            code = type(exc).__name__
        with engine.begin() as conn:
            conn.execute(text("SELECT app_webhook_finish(:i, :ok, :s, :e)"), {"i": r.id, "ok": ok, "s": status, "e": code})
        out["sent" if ok else "failed"] += 1
    with engine.begin() as conn:
        s = conn.execute(text("SELECT expired, purged FROM app_webhook_sweep()")).one()
    out["expired"], out["purged"] = s.expired, s.purged
    return out


def run() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO)
    engine = make_engine(os.environ["WORKER_DATABASE_URL"])
    interval = float(os.environ.get("WEBHOOKS_INTERVAL_S", "5"))
    settings = get_settings()
    if not webhooks.available(settings):
        log.info("webhooks not configured (WEBHOOK_ENCRYPTION_KEY): the dispatcher only keeps its heartbeat")
    while True:
        try:
            if webhooks.available(settings):
                n = run_once(engine, settings)
                if any(n.values()):
                    log.info("webhook run: %s", n)
            beat()
        except Exception:
            log.exception("webhook iteration failed; retrying")
        time.sleep(interval)


if __name__ == "__main__":
    run()
