from fastapi.testclient import TestClient

from app.main import app


def test_livez_and_version(seed):
    c = TestClient(app)
    assert c.get("/livez").json()["status"] == "alive"
    assert c.get("/version").json()["version"] == "0.1.0"


def test_readyz_ok_with_db(seed):
    assert TestClient(app).get("/readyz").status_code == 200


def test_readyz_fails_closed_when_db_down(seed, monkeypatch):
    from app.core import db
    monkeypatch.setattr("app.api.routes.get_engine", lambda: db.make_engine("postgresql://x:y@127.0.0.1:1/z"))
    r = TestClient(app).get("/readyz")
    assert r.status_code == 503
