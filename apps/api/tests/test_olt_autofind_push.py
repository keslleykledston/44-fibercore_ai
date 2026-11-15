"""ADR-0055: the Edge's periodic `olt.autofind` read. Same closed typed shape as the on-demand read, the OLT must be the Edge's own, the tenant flag decides, and the read becomes
`edge_read` sightings plus the cache's `routine` read. Nothing here reaches equipment or authorises anything."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import agent, hdr, snap
from tests.test_olt_query import on  # noqa: F401  (fixture: the olt_query flag, needed only to READ the cache through its route)
from tests.test_onu_discovery import _on

ENTRY = {"pon_path": "0/1/3", "serial": "48575443AABB0001", "vendor": "HWTC", "equipment": "EG8145V5", "found_at": "2026-11-14T10:20:30-04:00"}


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'onu_discovery'"))
        c.execute(text("DELETE FROM onu_discovery_observations"))
        c.execute(text("DELETE FROM olt_query_latest WHERE query_id = 'olt.autofind'"))


def _olt(client, seed, inv, key="a1", **kw):
    name = f"OLT-AF{uuid4().hex[:6]}"
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, key), json=snap(inv, key, name=name, **kw)).status_code == 202
    return name


def _push(client, inv, name, entries, key="a1", when=None):
    return client.post("/v1/edge/olt-autofind", headers=agent(client, inv, key),
                       json={"edge_id": str(inv[key]["edge"]), "observed_at": (when or datetime.now(UTC)).isoformat(), "name": name, "entries": entries})


def test_a_pushed_read_fills_the_queue_and_the_cache_and_an_empty_one_is_valid(client, seed, inv, migrated, on):  # noqa: F811
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    name = _olt(client, seed, inv)
    olt = next(o["id"] for o in client.get("/v1/olts?limit=1000", headers=h).json() if o["name"] == name)
    r = _push(client, inv, name, [])
    assert r.status_code == 202 and r.json()["status"] == "accepted" and r.json()["created"] == 0, r.text
    r = _push(client, inv, name, [ENTRY])
    assert r.status_code == 202 and r.json()["created"] == 1, r.text
    q = client.get(f"/v1/olts/{olt}/onus/unregistered", headers=h).json()
    assert [i["serial"] for i in q["items"]] == ["48575443AABB0001"]
    assert q["items"][0]["authoritative"] is True and q["items"][0]["authorization"] == "not_available"
    latest = client.get(f"/v1/olts/{olt}/queries/olt.autofind/latest", headers=h)
    assert latest.status_code == 200 and latest.json()["source"] == "routine" and latest.json()["data"] == {"entries": [ENTRY]}
    # the same list again changes nothing in the queue but counts as seen
    r = _push(client, inv, name, [ENTRY], when=datetime.now(UTC) + timedelta(seconds=1))
    assert r.json()["created"] == 0 and r.json()["updated"] == 1
    # the on-demand sync accepts the periodic read as an equipment read
    r = client.post(f"/v1/olts/{olt}/onus/unregistered/sync", headers=h)
    assert r.status_code == 200, r.text


def test_the_push_is_refused_when_the_shape_the_olt_or_the_edge_is_wrong(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    name = _olt(client, seed, inv)
    assert _push(client, inv, name, [{**ENTRY, "password": "x"}]).status_code == 422     # no registration credential, no extra key
    assert _push(client, inv, name, [{**ENTRY, "serial": "bad serial"}]).status_code == 422
    assert _push(client, inv, "OLT-DOES-NOT-EXIST", []).status_code == 404
    other = {"edge_id": str(inv["a1"]["edge"]), "observed_at": datetime.now(UTC).isoformat(), "name": name, "entries": []}
    assert client.post("/v1/edge/olt-autofind", headers=agent(client, inv, "a2"), json=other).status_code == 403   # a token of another Edge: not bound to the one it names
    body = {"edge_id": str(inv["a2"]["edge"]), "observed_at": datetime.now(UTC).isoformat(), "name": name, "entries": []}
    assert client.post("/v1/edge/olt-autofind", headers=agent(client, inv, "a2"), json=body).status_code == 409   # the OLT belongs to a1's Edge
    future = datetime.now(UTC) + timedelta(hours=1)
    assert _push(client, inv, name, [], when=future).status_code == 422
    assert _push(client, inv, name, [ENTRY] * 2).status_code == 422                          # a serial listed twice is not the closed shape


def test_with_the_flag_off_the_push_is_ignored_and_stores_nothing(client, seed, inv, migrated):
    name = _olt(client, seed, inv)
    r = _push(client, inv, name, [ENTRY])
    assert r.status_code == 202 and r.json() == {"status": "ignored_feature_off"}
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM onu_discovery_observations")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM olt_query_latest WHERE query_id = 'olt.autofind'")).scalar() == 0


def test_another_tenants_edge_cannot_push_into_this_olt(client, seed, inv, migrated):
    _on(migrated, seed["A"])
    _on(migrated, seed["B"])
    name = _olt(client, seed, inv)
    body = {"edge_id": str(inv["b1"]["edge"]), "observed_at": datetime.now(UTC).isoformat(), "name": name, "entries": [ENTRY]}
    r = client.post("/v1/edge/olt-autofind", headers=agent(client, inv, "b1"), json=body)
    assert r.status_code in (404, 409), r.text   # RLS hides the OLT of tenant A from tenant B's Edge
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM onu_discovery_observations")).scalar() == 0
