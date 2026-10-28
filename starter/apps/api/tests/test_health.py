import os
from fastapi.testclient import TestClient
from app.main import app


def test_liveness():
    assert TestClient(app).get("/livez").json()["status"] == "alive"


def test_demo_registry_not_public(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert TestClient(app).get("/modules").status_code == 403


def test_readiness_fails_closed_without_db(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert TestClient(app).get("/readyz").status_code == 503
