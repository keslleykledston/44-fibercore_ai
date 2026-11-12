"""Observability (ADR-0043): the API's RED metrics, GET /metrics access, and the DB/backup/disk exporter. No tenant data may reach a metric."""
import os
import re
import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import metrics as m
from app.core.db import make_engine
from app.core.settings import get_settings
from app.workers import metrics_exporter as ex

TOKEN = "metrics-token-with-more-than-32-characters!!"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
IP_RE = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield TOKEN
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    get_settings.cache_clear()


# ---- registry / exposition (pure) ---------------------------------------------------------------
def test_registry_renders_counters_and_a_cumulative_histogram():
    r = m.Registry()
    r.observe("GET", "/v1/x/{id}", 200, 0.004)
    r.observe("GET", "/v1/x/{id}", 200, 0.3)
    r.observe("GET", "/v1/x/{id}", 503, 20.0)
    out = r.render(version="9.9", started_at=1700000000.0)
    assert 'fibercore_http_requests_total{method="GET",route="/v1/x/{id}",code="200"} 2' in out
    assert 'fibercore_http_requests_total{method="GET",route="/v1/x/{id}",code="503"} 1' in out
    assert 'fibercore_http_request_duration_seconds_bucket{method="GET",route="/v1/x/{id}",le="0.005"} 1' in out
    assert 'fibercore_http_request_duration_seconds_bucket{method="GET",route="/v1/x/{id}",le="0.5"} 2' in out      # cumulative: 0.004 and 0.3
    assert 'fibercore_http_request_duration_seconds_bucket{method="GET",route="/v1/x/{id}",le="+Inf"} 3' in out
    assert 'fibercore_http_request_duration_seconds_count{method="GET",route="/v1/x/{id}"} 3' in out
    assert 'fibercore_api_build_info{version="9.9"} 1' in out
    assert out.endswith("\n")


def test_method_and_label_values_cannot_blow_up_cardinality_or_break_the_format():
    r = m.Registry()
    r.observe("PURGE", "unmatched", 404, 0.001)
    r.observe("get", "unmatched", 404, 0.001)
    out = r.render(version='v"1\\', started_at=0.0)
    assert out.count('method="OTHER"') >= 1 and 'method="PURGE"' not in out
    assert 'version="v\\"1\\\\"' in out   # quotes and backslashes are escaped


# ---- GET /metrics access ------------------------------------------------------------------------
def has_series(body: str, name: str) -> bool:
    return re.search(rf"^{name}(\{{.*\}})? ", body, re.M) is not None


def test_metrics_is_a_404_until_a_token_is_configured(client):
    get_settings.cache_clear()
    assert client.get("/metrics").status_code == 404
    assert client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 404   # even with a "token": the feature is off


def test_metrics_needs_the_exact_bearer_token(client, token):
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": f"Basic {TOKEN}"}).status_code == 401
    r = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert r.headers["cache-control"] == "no-store"


def test_a_short_token_stops_the_settings_instead_of_opening_the_route_weakly(monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "short")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError):
            get_settings()
    finally:
        monkeypatch.delenv("METRICS_TOKEN", raising=False)
        get_settings.cache_clear()


def test_requests_are_counted_by_route_template_not_raw_path_and_leak_no_identifiers(client, token, seed):
    h = {"Authorization": f"Bearer {TOKEN}"}
    secret_id = str(uuid.uuid4())
    for _ in range(3):
        client.get(f"/v1/cpes/{secret_id}/state")        # a templated route (401 without a token: the TEMPLATE is the label)
    client.get(f"/no/such/route/{secret_id}")             # matches nothing
    client.get("/livez")
    body = client.get("/metrics", headers=h).text
    assert 'route="/livez"' in body
    assert 'route="unmatched"' in body
    assert secret_id not in body and not UUID_RE.search(body.replace(str(seed["A"]), "")), "an identifier reached a label"
    assert "/no/such/route" not in body
    assert not IP_RE.search(body)
    assert 'route="/v1/cpes/{cpe_id}/state"' in body   # the template, not the value


def test_an_unhandled_exception_is_counted_as_a_500_and_still_raises(token):
    from fastapi.testclient import TestClient

    from app.api.metrics import REGISTRY
    from app.main import app

    async def boom():
        raise RuntimeError("boom")

    app.add_api_route("/__obs_boom", boom, include_in_schema=False)
    try:
        c = TestClient(app, raise_server_exceptions=False)
        assert c.get("/__obs_boom").status_code == 500
        out = REGISTRY.render(version="x", started_at=0.0)
        assert 'route="/__obs_boom",code="500"' in out
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/__obs_boom"]


# ---- exporter -----------------------------------------------------------------------------------
@pytest.fixture
def worker(worker_url):
    eng = make_engine(worker_url)
    yield eng
    eng.dispose()


def test_snapshot_function_is_executable_by_the_worker_role_only(worker, app_url, rbac_url):
    assert isinstance(ex.snapshot(worker), dict)
    for url in (app_url, rbac_url):
        eng = make_engine(url)
        try:
            with pytest.raises(DBAPIError), eng.begin() as c:
                c.execute(text("SELECT app_metrics_snapshot()"))
        finally:
            eng.dispose()
    with worker.begin() as c:   # the worker role still has no grant on the tables themselves
        for t in ("edges", "olts", "jobs"):
            with pytest.raises(DBAPIError), c.begin_nested():
                c.execute(text(f"SELECT 1 FROM {t} LIMIT 1"))  # noqa: S608 - fixed table names


def test_snapshot_counts_edges_olts_outbox_and_jobs_without_a_single_identifier(worker, migrated, seed):
    before = ex.snapshot(worker)
    t = seed["A"]
    with migrated.begin() as c:
        e_old = c.execute(text("INSERT INTO edges(tenant_id,name,last_heartbeat_at) VALUES (:t,'obs-old', now() - interval '9999999 seconds') RETURNING id"), {"t": t}).scalar()
        e_new = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'obs-never') RETURNING id"), {"t": t}).scalar()
        e_rev = c.execute(text("INSERT INTO edges(tenant_id,name,status) VALUES (:t,'obs-revoked','revoked') RETURNING id"), {"t": t}).scalar()
        c.execute(text("INSERT INTO olts(tenant_id,edge_id,name,vendor,observed_at) VALUES (:t,:e,'obs-olt-1','huawei', now() - interval '8888888 seconds')"), {"t": t, "e": e_old})
        c.execute(text("INSERT INTO olts(tenant_id,edge_id,name,vendor) VALUES (:t,:e,'obs-olt-2','huawei')"), {"t": t, "e": e_new})
        c.execute(text("INSERT INTO olts(tenant_id,edge_id,name,vendor) VALUES (:t,:e,'obs-olt-3','huawei')"), {"t": t, "e": e_rev})   # on a revoked Edge: not counted
        c.execute(text("INSERT INTO events_outbox(tenant_id,aggregate_type,aggregate_id,event_type,schema_version,payload,created_at) "
                       "VALUES (:t,'x',gen_random_uuid(),'obs.test','1','{}'::jsonb, now() - interval '7777777 seconds')"), {"t": t})
        for i, st in enumerate(("DISPATCHED", "SUCCEEDED")):
            c.execute(text("INSERT INTO jobs(tenant_id,edge_id,target_type,target_id,operation,intent_hash,idempotency_key,risk,required_approvals,status,requested_by,updated_at) "
                           "VALUES (:t,:e,'olt',gen_random_uuid(),'obs_op',repeat('a',64),:k,'R0',0,:s,gen_random_uuid(), now() - interval '6666666 seconds')"),
                      {"t": t, "e": e_old, "k": f"obs-{i}", "s": st})
    try:
        after = ex.snapshot(worker)
        assert after["edges_active"] == before["edges_active"] + 2
        assert after["edges_never_heartbeat"] == before["edges_never_heartbeat"] + 1
        assert after["edge_heartbeat_age_seconds_max"] >= 9999990
        assert after["olts_registered"] == before["olts_registered"] + 2
        assert after["olts_never_collected"] == before["olts_never_collected"] + 1
        assert after["olt_collection_age_seconds_max"] >= 8888880
        assert after["outbox_unpublished"] == before["outbox_unpublished"] + 1
        assert after["outbox_oldest_unpublished_age_seconds"] >= 7777770
        assert after["jobs"].get("DISPATCHED", 0) == before["jobs"].get("DISPATCHED", 0) + 1       # in flight: always counted
        assert after["jobs"].get("SUCCEEDED", 0) == before["jobs"].get("SUCCEEDED", 0)             # terminal and older than 24 h: not counted
        assert after["jobs_in_flight_oldest_age_seconds"] >= 6666660
        blob = str(after)
        assert not UUID_RE.search(blob) and "obs-" not in blob and not IP_RE.search(blob)
        assert set(after) == {"edges_active", "edges_never_heartbeat", "edge_heartbeat_age_seconds_max", "olts_registered", "olts_never_collected", "olt_collection_age_seconds_max",
                              "outbox_unpublished", "outbox_oldest_unpublished_age_seconds", "jobs", "jobs_in_flight_oldest_age_seconds", "organizations_without_api_trail"}
    finally:
        with migrated.begin() as c:
            c.execute(text("DELETE FROM jobs WHERE operation = 'obs_op'"))
            c.execute(text("DELETE FROM events_outbox WHERE event_type = 'obs.test'"))
            c.execute(text("DELETE FROM olts WHERE name LIKE 'obs-olt-%'"))
            c.execute(text("DELETE FROM edges WHERE name IN ('obs-old','obs-never','obs-revoked')"))


def test_exporter_job_states_match_the_table_constraint(migrated):
    with migrated.begin() as c:
        d = c.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'jobs'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%PREVIEWED%'")).scalar()
    assert set(re.findall(r"'([A-Z_]+)'", d)) == set(ex.JOB_STATES)


def test_exporter_text_has_every_documented_name_and_a_failed_snapshot_publishes_no_database_series(worker, tmp_path):
    (tmp_path / "fibercore-prod-20260101.dump.done").write_text("")
    c = ex.Collector(worker, str(tmp_path), "fibercore-prod-*.dump.done")
    body = c.render()
    names = set(re.findall(r"^# TYPE (\S+) ", body, re.M))
    assert names == set(m.EXPORTER_METRICS), names ^ set(m.EXPORTER_METRICS)
    assert 'fibercore_jobs{state="DISPATCHED"}' in body and 'fibercore_disk_free_ratio{fs="backup"}' in body and "fibercore_exporter_db_up 1" in body

    def broken(_e):
        raise RuntimeError("db down")

    bad = ex.Collector(worker, str(tmp_path), "fibercore-prod-*.dump.done", snap=broken).render()
    assert "fibercore_exporter_db_up 0" in bad
    assert not any(has_series(bad, n) for n in ("fibercore_edges_active", "fibercore_outbox_unpublished", "fibercore_jobs"))
    assert "fibercore_backup_files_found 1" in bad   # the backup/disk part does not depend on the database


def test_the_database_part_is_cached_for_a_few_seconds(worker):
    calls = []
    clock = [1000.0]

    def counting(_e):
        calls.append(1)
        return {"edges_active": 0, "edges_never_heartbeat": 0, "edge_heartbeat_age_seconds_max": None, "olts_registered": 0, "olts_never_collected": 0, "olt_collection_age_seconds_max": None,
                "outbox_unpublished": 0, "outbox_oldest_unpublished_age_seconds": None, "jobs": {"WEIRD": 2}, "jobs_in_flight_oldest_age_seconds": None}

    c = ex.Collector(worker, "", "x", now=lambda: clock[0], snap=counting)
    first = c.render()
    c.render()
    assert len(calls) == 1
    clock[0] += ex.CACHE_S + 1
    c.render()
    assert len(calls) == 2
    assert 'fibercore_jobs{state="WEIRD"} 2' in first                      # an unknown state is shown, not dropped
    assert not has_series(first, "fibercore_edge_heartbeat_age_seconds_max")       # absent, not 0, when there is no Edge that ever beat
    assert "fibercore_backup_files_found 0" in first and 'fs="backup"' not in first   # no backup dir configured


def test_backup_age_reads_only_the_marker_mtime(tmp_path):
    old = tmp_path / "fibercore-prod-1.dump.done"
    new = tmp_path / "fibercore-prod-2.dump.done"
    other = tmp_path / "other-1.dump.done"
    for p in (old, new, other):
        p.write_text("")
    os.utime(old, (1000, 1000)); os.utime(new, (5000, 5000)); os.utime(other, (9000, 9000))
    body = m.render_families(ex.backup_families(str(tmp_path), "fibercore-prod-*.dump.done", now=6000))
    assert "fibercore_backup_files_found 2" in body and "fibercore_backup_last_success_timestamp_seconds 5000" in body
    empty = m.render_families(ex.backup_families(str(tmp_path / "missing"), "fibercore-prod-*.dump.done"))
    assert "fibercore_backup_files_found 0" in empty and not has_series(empty, "fibercore_backup_last_success_timestamp_seconds")


def test_an_unreadable_or_missing_backup_directory_is_told_apart_from_an_empty_one(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "fibercore-prod-1.dump.done").write_text("")
    locked.chmod(0o000)
    try:
        def get(d):
            return m.render_families(ex.backup_families(str(d), "fibercore-prod-*.dump.done"))
        assert "fibercore_backup_dir_readable 1" in get(empty) and "fibercore_backup_files_found 0" in get(empty)      # empty: readable, no marker
        for bad in (tmp_path / "missing", "", locked):
            body = get(bad)
            assert "fibercore_backup_dir_readable 0" in body and "fibercore_backup_files_found 0" in body, bad
            assert not has_series(body, "fibercore_backup_last_success_timestamp_seconds")
    finally:
        locked.chmod(0o700)


def test_disk_ratio_is_between_zero_and_one_and_skips_a_missing_path(tmp_path):
    body = m.render_families(ex.disk_families({"docker": "/", "gone": str(tmp_path / "nope")}))
    v = float(re.search(r'fibercore_disk_free_ratio\{fs="docker"\} (\S+)', body).group(1))
    assert 0.0 <= v <= 1.0 and 'fs="gone"' not in body


def test_http_handler_serves_metrics_and_healthz_only(worker):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    srv = ThreadingHTTPServer(("127.0.0.1", 0), ex.make_handler(ex.Collector(worker, "", "x")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        assert urllib.request.urlopen(base + "/healthz", timeout=5).read() == b"ok\n"  # noqa: S310
        r = urllib.request.urlopen(base + "/metrics", timeout=5)  # noqa: S310
        assert r.status == 200 and b"fibercore_exporter_db_up 1" in r.read()
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/anything", timeout=5)  # noqa: S310
        assert e.value.code == 404
    finally:
        srv.shutdown()
        srv.server_close()
    assert time.time() > 0
