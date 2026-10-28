"""Integration tests run against a real PostgreSQL (RLS cannot be mocked).

Set TEST_ADMIN_DATABASE_URL (owner role) e.g. postgresql://fibercore:pw@127.0.0.1:55432/fibercore_test
`make test-api` starts a throwaway container for this.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy import create_engine, text

APP_PW = "app_role_test_pw_0123456789"
WORKER_PW = "worker_role_test_pw_0123456789"
JWT_SECRET = "test-secret-with-more-than-32-characters!!"
PII_KEY = "pii-hmac-key-with-more-than-32-characters!!"
API_DIR = Path(__file__).resolve().parents[1]
MANIFEST = API_DIR.parents[1] / "configs" / "modules.yaml"


def _admin_url() -> str:
    url = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("TEST_ADMIN_DATABASE_URL not set (needs PostgreSQL)", allow_module_level=True)
    return url


@pytest.fixture(scope="session")
def admin_url() -> str:
    return _admin_url()


@pytest.fixture(scope="session")
def app_url(admin_url: str) -> str:
    p = urlparse(admin_url)
    return urlunparse(p._replace(netloc=f"fibercore_app:{APP_PW}@{p.hostname}:{p.port}"))


@pytest.fixture(scope="session")
def worker_url(admin_url: str) -> str:
    p = urlparse(admin_url)
    return urlunparse(p._replace(netloc=f"fibercore_worker:{WORKER_PW}@{p.hostname}:{p.port}"))


@pytest.fixture(scope="session", autouse=True)
def migrated(admin_url: str, app_url: str):
    eng = create_engine(admin_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW, "WORKER_DB_PASSWORD": WORKER_PW}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=True)
    os.environ.update(
        DATABASE_URL=app_url, JWT_SECRET=JWT_SECRET, PII_HMAC_KEY=PII_KEY, MODULE_MANIFEST=str(MANIFEST), NATS_MONITOR_URL=""
    )
    from app.core import db, settings
    settings.get_settings.cache_clear(); db.get_engine.cache_clear()
    yield eng


@pytest.fixture(scope="session")
def seed(migrated):
    """Two tenants (A, B), users: alice(A admin), bob(B admin), carol(A auditor + B engineer), dave(A noc_n1)."""
    from app.core.security import hash_secret
    ids: dict = {}
    pw = hash_secret("correct horse battery")
    with migrated.begin() as c:
        for k in ("A", "B"):
            ids[k] = c.execute(text("INSERT INTO tenants(name) VALUES (:n) RETURNING id"), {"n": f"Tenant {k}"}).scalar()
        for k in ("alice", "bob", "carol", "dave"):
            ids[k] = c.execute(
                text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:e,:h) RETURNING id"),
                {"e": f"{k}@example.com", "h": pw}).scalar()
        for t, u, r in [("A", "alice", "isp_admin"), ("B", "bob", "isp_admin"), ("A", "carol", "auditor"),
                        ("B", "carol", "engineer"), ("A", "dave", "noc_n1")]:
            c.execute(text("INSERT INTO tenant_memberships VALUES (:t,:u,:r)"), {"t": ids[t], "u": ids[u], "r": r})
        ids["sa_secret"] = "svc-secret-value-123"
        ids["sa"] = c.execute(
            text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash) VALUES (:t,'edge-bot','engineer',:h) RETURNING id"),
            {"t": ids["A"], "h": hash_secret(ids["sa_secret"])}).scalar()
    return ids


@pytest.fixture
def client(seed):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def login(client, who: str) -> dict:
    r = client.post("/v1/auth/token", json={"email": f"{who}@example.com", "password": "correct horse battery"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---- shared inventory helpers (session scoped: edges/agents are created once) --------------------
from datetime import UTC, datetime, timedelta  # noqa: E402

from app.core.security import hash_secret  # noqa: E402

SECRET = "inv-agent-secret"


def _now(delta_s: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=delta_s)).isoformat()


@pytest.fixture(scope="session")
def inv(seed, migrated):
    out = {}
    with migrated.begin() as c:
        for key, tenant in (("a1", "A"), ("a2", "A"), ("b1", "B")):
            eid = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,:n) RETURNING id"),
                            {"t": seed[tenant], "n": f"inv-{key}"}).scalar()
            sa = c.execute(
                text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,:n,'edge_agent',:h,:e) RETURNING id"),
                {"t": seed[tenant], "n": f"inv-agent-{key}", "h": hash_secret(SECRET), "e": eid}).scalar()
            out[key] = {"edge": eid, "sa": sa}
    return out


def agent(client, inv, key):
    r = client.post("/v1/auth/service-token", json={"client_id": str(inv[key]["sa"]), "client_secret": SECRET})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def snap(inv, key="a1", name="OLT-1", observed=None, **kw):
    body = {"edge_id": str(inv[key]["edge"]), "observed_at": observed or _now(), "name": name, "vendor": "huawei",
            "model": "MA5800-X7", "firmware": "R018", "driver_level": "observed",
            "pons": [{"pon_path": "0/1/0", "status": "up"}],
            "onus": [{"serial": "HWTC00000001", "pon_path": "0/1/0", "status": "online", "rx_dbm": -21.5},
                     {"serial": "HWTC00000002", "pon_path": "0/1/0", "status": "los", "rx_dbm": None}]}
    body.update(kw)
    return body


def hdr(client, who, seed, tenant):
    return {**login(client, who), "X-Workspace-ID": str(seed[tenant])}


