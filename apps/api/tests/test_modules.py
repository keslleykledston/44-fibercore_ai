from app.core.modules import Infra, evaluate, load_manifest
from tests.conftest import MANIFEST, login


def _by_id(infra):
    return {m["id"]: m for m in evaluate(load_manifest(MANIFEST), infra)}


def test_status_honest_when_all_up():
    m = _by_id(Infra(postgres=True, nats=True))
    assert m["identity-access"]["status"] == "healthy"
    assert m["template-catalog"]["status"] == "unknown"  # never faked healthy
    assert m["acs-cwmp"]["status"] == "disabled"  # feature flag off


def test_postgres_down_marks_core_unhealthy():
    m = _by_id(Infra(postgres=False, nats=True))
    assert m["identity-access"]["status"] == "unhealthy"
    assert m["platform-manager"]["status"] == "unhealthy"


def test_optional_nats_down_degrades_not_down():
    m = _by_id(Infra(postgres=True, nats=False))
    assert m["identity-access"]["status"] == "healthy"  # nats not a dependency of identity-access
    assert m["platform-manager"]["status"] == "healthy"


def test_endpoint_requires_auth_and_returns_registry(client, seed):
    h = login(client, "alice")
    r = client.get("/v1/platform/modules", headers=h)
    assert r.status_code == 200 and {m["id"] for m in r.json()} >= {"identity-access", "copilot"}


def test_versions_endpoint(client, seed):
    r = client.get("/v1/platform/versions", headers=login(client, "alice"))
    assert r.status_code == 200 and r.json()[0] == {"module": "api-core", "version": "0.1.0"}
