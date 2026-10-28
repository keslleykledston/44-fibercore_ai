import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "mocks"))
import genieacs_nbi  # noqa: E402
from edge import MockEdge, NotAllowed  # noqa: E402

from app.core.db import make_engine, scoped_connection  # noqa: E402
from app.core.security import hash_secret  # noqa: E402
from tests.conftest import login  # noqa: E402

NBI = "http://genieacs.lab:7557"


@pytest.fixture(scope="module")
def edge_env(seed, migrated):
    with migrated.begin() as c:
        eid = c.execute(text("INSERT INTO edges(tenant_id,name,site_name) VALUES (:t,'edge-a1','POP A') RETURNING id"),
                        {"t": seed["A"]}).scalar()
        c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'edge-b1')"), {"t": seed["B"]})
        sec = "edge-agent-secret-xyz"
        sa = c.execute(
            text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,'edge-a1-agent','edge_agent',:h,:e) RETURNING id"),
            {"t": seed["A"], "h": hash_secret(sec), "e": eid}).scalar()
        eid2 = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'edge-a2') RETURNING id"), {"t": seed["A"]}).scalar()
        sa2 = c.execute(
            text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,'edge-a2-agent','edge_agent',:h,:e) RETURNING id"),
            {"t": seed["A"], "h": hash_secret(sec), "e": eid2}).scalar()
    return {"edge": eid, "sa": sa, "secret": sec, "edge2": eid2, "sa2": sa2}


def token(client, edge_env):
    r = client.post("/v1/auth/service-token", json={"client_id": str(edge_env["sa"]), "client_secret": edge_env["secret"]})
    return r.json()["access_token"]


def make_edge(client, seed, edge_env, allowlist=("genieacs.lab:7557",), nbi_url=NBI):
    nbi_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=genieacs_nbi.create_app()))
    return MockEdge(edge_id=str(edge_env["edge"]), tenant_id=str(seed["A"]), version="0.0.1-mock",
                    token=token(client, edge_env), gateway=client, nbi_url=nbi_url, nbi_client=nbi_http,
                    allowlist=set(allowlist))


def test_heartbeat_marks_online_and_listing_is_tenant_scoped(client, seed, edge_env):
    edge = make_edge(client, seed, edge_env)
    assert edge.heartbeat() == 204
    h = {**login(client, "alice"), "X-Workspace-ID": str(seed["A"])}
    rows = client.get("/v1/edges", headers=h).json()
    assert [r["name"] for r in rows] == ["edge-a1", "edge-a2"] and rows[0]["status"] == "online" and rows[1]["status"] == "unknown" and rows[0]["version"] == "0.0.1-mock"
    hb = {**login(client, "bob"), "X-Workspace-ID": str(seed["B"])}
    assert [r["name"] for r in client.get("/v1/edges", headers=hb).json()] == ["edge-b1"]


def test_stale_heartbeat_reads_offline_not_online(client, seed, edge_env, migrated):
    make_edge(client, seed, edge_env).heartbeat()
    with migrated.begin() as c:
        c.execute(text("UPDATE edges SET last_heartbeat_at = now() - interval '10 minutes' WHERE id=:i"), {"i": edge_env["edge"]})
    h = {**login(client, "alice"), "X-Workspace-ID": str(seed["A"])}
    assert client.get("/v1/edges", headers=h).json()[0]["status"] == "offline"


def test_heartbeat_rejections(client, seed, edge_env, migrated):
    tok = {"Authorization": f"Bearer {token(client, edge_env)}"}
    body = {"edge_id": str(edge_env["edge"]), "tenant_id": str(seed["A"]), "version": "x", "sent_at": "2026-10-27T00:00:00Z"}
    assert client.post("/v1/edge/heartbeat", json=body).status_code == 401
    assert client.post("/v1/edge/heartbeat", headers=tok, json={**body, "tenant_id": str(seed["B"])}).status_code == 403
    assert client.post("/v1/edge/heartbeat", headers=tok, json={**body, "edge_id": str(uuid4())}).status_code == 403
    # a human user without edge:heartbeat cannot post heartbeats
    assert client.post("/v1/edge/heartbeat", headers=login(client, "alice"), json=body).status_code == 403
    # edge_agent token cannot read anything else
    assert client.get("/v1/edges", headers=tok).status_code == 403
    assert client.get("/v1/audit", headers=tok).status_code == 403
    with migrated.begin() as c:
        c.execute(text("UPDATE edges SET status='revoked' WHERE id=:i"), {"i": edge_env["edge"]})
    assert client.post("/v1/edge/heartbeat", headers=tok, json=body).status_code == 404  # revoked edge refused
    with migrated.begin() as c:
        c.execute(text("UPDATE edges SET status='unknown' WHERE id=:i"), {"i": edge_env["edge"]})


def test_runtime_role_cannot_register_or_delete_edges(seed, app_url):
    eng = make_engine(app_url)
    for stmt in ("INSERT INTO edges(tenant_id,name) VALUES (:t,'rogue')", "DELETE FROM edges", "UPDATE edges SET name='x'"):
        with pytest.raises(DBAPIError), scoped_connection(eng, tenant_id=seed["A"]) as c:
            c.execute(text(stmt), {"t": seed["A"]})


def test_mock_edge_allowlist_blocks_ssrf(client, seed, edge_env):
    with pytest.raises(NotAllowed):
        make_edge(client, seed, edge_env, nbi_url="http://169.254.169.254:80")
    with pytest.raises(NotAllowed):
        make_edge(client, seed, edge_env, allowlist=("other.host:7557",))


def test_mock_nbi_is_read_only_and_projection_works(client, seed, edge_env):
    edge = make_edge(client, seed, edge_env)
    devices = asyncio.run(edge.collect_devices())
    assert {d["_id"] for d in devices} == {"00259E-HG8245H-ZTEG00000001", "A0B1C2-F670L-ZTEG00000002"}
    assert all("InternetGatewayDevice" not in d and "Device" not in d for d in devices)  # projection honoured

    async def write_attempt():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=genieacs_nbi.create_app()), base_url=NBI) as c:
            return [(await c.request(m, "/devices/x/tasks", json={})).status_code for m in ("POST", "PUT", "PATCH", "DELETE")]

    assert asyncio.run(write_attempt()) == [405, 405, 405, 405]


def test_edge_frame_schema_validates_samples():
    schema = json.loads((ROOT / "contracts" / "edge-frame.schema.json").read_text())
    v = Draft202012Validator(schema)
    ok = {"schema_version": "1.0", "type": "heartbeat", "edge_id": str(uuid4()), "tenant_id": str(uuid4()), "seq": 1,
          "sent_at": "2026-10-27T00:00:00Z"}
    assert not list(v.iter_errors(ok))
    assert list(v.iter_errors({**ok, "type": "shell_exec"}))  # no free-form command frame
    assert list(v.iter_errors({**ok, "type": "job"}))  # job requires body
    assert list(v.iter_errors({**ok, "extra": 1}))


def test_agent_credential_is_bound_to_its_own_edge(client, seed, edge_env, migrated):
    """Two edge_agent accounts in one tenant: each may only heartbeat its own edge."""
    tok2 = client.post("/v1/auth/service-token", json={"client_id": str(edge_env["sa2"]), "client_secret": edge_env["secret"]})
    h2 = {"Authorization": f"Bearer {tok2.json()['access_token']}"}
    body = {"edge_id": str(edge_env["edge"]), "tenant_id": str(seed["A"]), "version": "evil", "sent_at": "2026-10-27T00:00:00Z"}
    assert client.post("/v1/edge/heartbeat", headers=h2, json=body).status_code == 403  # edge-a2 token vs edge-a1
    with migrated.connect() as c:
        assert c.execute(text("SELECT version FROM edges WHERE id=:i"), {"i": edge_env["edge"]}).scalar() != "evil"
    assert client.post("/v1/edge/heartbeat", headers=h2, json={**body, "edge_id": str(edge_env["edge2"]), "version": "ok"}).status_code == 204


def test_db_constraint_edge_agent_requires_edge(seed, migrated):
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash) VALUES (:t,'orphan','edge_agent','x')"), {"t": seed["A"]})
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,'bad','engineer','x',:e)"),
                  {"t": seed["A"], "e": seed["A"]})


def test_runtime_cannot_change_status_or_touch_revoked_edge(seed, app_url, edge_env, migrated):
    eng = make_engine(app_url)
    with pytest.raises(DBAPIError), scoped_connection(eng, tenant_id=seed["A"]) as c:
        c.execute(text("UPDATE edges SET status='online'"))  # column not granted
    with migrated.begin() as c:
        c.execute(text("UPDATE edges SET status='revoked' WHERE id=:i"), {"i": edge_env["edge"]})
    try:
        with scoped_connection(eng, tenant_id=seed["A"]) as c:
            n = c.execute(text("UPDATE edges SET version='hijack' WHERE id=:i"), {"i": edge_env["edge"]}).rowcount
        assert n == 0  # RESTRICTIVE policy hides revoked rows from UPDATE
    finally:
        with migrated.begin() as c:
            c.execute(text("UPDATE edges SET status='unknown' WHERE id=:i"), {"i": edge_env["edge"]})
