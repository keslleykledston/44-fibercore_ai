"""Minimal health and module-manifest demo. No authenticated business endpoints yet.

DEMO_MODE=true is intentionally unsafe for public exposure. This is a lab scaffold.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import psycopg
except ImportError:  # Test harness without DB driver; production image installs psycopg.
    psycopg = None
import yaml
from fastapi import FastAPI, HTTPException

app = FastAPI(title="FiberCore AI bootstrap", version="0.0.1-demo")


def postgres_available() -> bool:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn or psycopg is None:
        return False
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() == (1,)
    except psycopg.Error:
        return False


def load_manifest() -> list[dict]:
    path = Path(os.environ.get("MODULE_MANIFEST", "/app/configs/modules.yaml"))
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    return obj.get("modules", [])


@app.get("/livez")
def livez() -> dict:
    return {"status": "alive", "service": "api-core"}


@app.get("/readyz")
def readyz() -> dict:
    if not postgres_available():
        raise HTTPException(status_code=503, detail="PostgreSQL not ready")
    return {"status": "ready", "service": "api-core"}


@app.get("/version")
def version() -> dict:
    return {"service": "api-core", "version": "0.0.1-demo", "environment": "scaffold"}


@app.get("/modules")
def modules() -> list[dict]:
    if os.environ.get("DEMO_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Demo endpoint disabled; implement RBAC before production")
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for module in load_manifest():
        # Static status is intentionally NOT reported as healthy; real probe machinery pending.
        status = "disabled" if module.get("feature_flag") is False else "unknown"
        out.append({"id": module["id"], "version": module["version"], "status": status,
                    "capabilities": module.get("capabilities", []), "checked_at": now,
                    "reason": "bootstrap registry only, no runtime probes implemented"})
    return out
