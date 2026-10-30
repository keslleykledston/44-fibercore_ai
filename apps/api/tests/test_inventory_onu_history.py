"""History of ONU state changes: written only by the trigger on `onus`, so it records exactly what the ingest applied, and read by the history,
the unstable list and the offline report."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import _now, agent, hdr, snap

DAY = 86400


def _push(client, inv, name, serial, status, ago_s, pon="0/1/0"):
    body = snap(inv, name=name, observed=_now(-ago_s), onus=[{"serial": serial, "pon_path": pon, "status": status}])
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=body)
    assert r.status_code == 202, r.text
    return r.json()


def _onu(client, seed, serial):
    return client.get(f"/v1/onus?serial={serial}", headers=hdr(client, "alice", seed, "A")).json()[0]["id"]


@pytest.fixture
def olt(migrated):
    name = f"OLT-H{uuid4().hex[:6]}"
    yield name
    with migrated.begin() as c:   # the ONUs (and their history, by cascade) must not leak into the counts of the other modules
        c.execute(text("DELETE FROM olts WHERE name = :n"), {"n": name})


def _timeline(client, inv, name, serial, steps):
    for status, ago in steps:
        _push(client, inv, name, serial, status, ago)


def test_history_and_the_numbers_for_a_known_timeline(client, seed, inv, olt):
    s = f"HIST{uuid4().hex[:8].upper()}"
    # online 10 d ago, down 5 d ago, up 4 d ago, down 2 d ago (still down): 2 drops, 24 h + 48 h down, 240 h known
    _timeline(client, inv, olt, s, [("online", 10 * DAY), ("offline", 5 * DAY), ("online", 4 * DAY), ("los", 2 * DAY)])
    h = hdr(client, "alice", seed, "A")
    j = client.get(f"/v1/onus/{_onu(client, seed, s)}/history?days=30", headers=h).json()
    assert [(e["from"], e["to"], e["baseline"]) for e in j["events"]] == [("online", "los", False), ("offline", "online", False), ("online", "offline", False), (None, "online", True)]
    sm = j["summary"]
    assert sm["drops"] == 2 and abs(sm["offline_hours"] - 72) < 0.2 and abs(sm["known_hours"] - 240) < 0.2 and abs(sm["availability_pct"] - 70.0) < 0.2
    # a shorter window clips the segments: the last 3 days hold 1 drop and 48 h down out of 72 h
    short = client.get(f"/v1/onus/{_onu(client, seed, s)}/history?days=3", headers=h).json()["summary"]
    assert short["drops"] == 1 and abs(short["offline_hours"] - 48) < 0.2 and abs(short["known_hours"] - 72) < 0.2


def test_only_real_changes_are_logged(client, seed, inv, olt):
    s = f"ONLY{uuid4().hex[:8].upper()}"
    _push(client, inv, olt, s, "online", 3600)
    _push(client, inv, olt, s, "online", 1800)            # same state again: nothing happened
    _push(client, inv, olt, s, "offline", 900)
    _push(client, inv, olt, s, "online", 5000)            # an OLDER snapshot is ignored by the ingest: it must log nothing either
    _push(client, inv, olt, s, "offline", 900)            # a replay of the very same observation
    ev = client.get(f"/v1/onus/{_onu(client, seed, s)}/history", headers=hdr(client, "alice", seed, "A")).json()["events"]
    assert [(e["from"], e["to"]) for e in ev] == [("online", "offline"), (None, "online")]


def test_unknown_is_neither_up_nor_down_and_is_not_a_drop(client, seed, inv, olt):
    s = f"UNK{uuid4().hex[:8].upper()}"
    _timeline(client, inv, olt, s, [("unknown", 8 * DAY), ("offline", 6 * DAY), ("online", 5 * DAY), ("unknown", 4 * DAY), ("offline", 2 * DAY)])
    sm = client.get(f"/v1/onus/{_onu(client, seed, s)}/history?days=30", headers=hdr(client, "alice", seed, "A")).json()["summary"]
    # drops: none (unknown -> offline and a baseline are not drops; online -> unknown is not a drop). down: 24 h + 48 h. known: 8d-4d minus the unknown stretch
    assert sm["drops"] == 0
    assert abs(sm["offline_hours"] - 72) < 0.2
    assert abs(sm["known_hours"] - 96) < 0.3     # offline 6d..5d (24) + online 5d..4d (24) + offline 2d..now (48); both unknown stretches are left out


def test_the_unstable_list_and_the_offline_report(client, seed, inv, olt):
    flappy, calm = f"FLAP{uuid4().hex[:6].upper()}", f"CALM{uuid4().hex[:6].upper()}"
    steps = [("online", 9 * DAY), ("offline", 8 * DAY), ("online", 7 * DAY), ("offline", 6 * DAY), ("online", 5 * DAY), ("offline", 4 * DAY), ("online", 3 * DAY), ("offline", 2 * DAY)]
    for status, ago in steps:        # one snapshot carries both ONUs: the flapping one changes, the calm one stays online
        body = snap(inv, name=olt, observed=_now(-ago), onus=[{"serial": flappy, "pon_path": "0/1/0", "status": status}, {"serial": calm, "pon_path": "0/1/0", "status": "online"}])
        assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    h = hdr(client, "alice", seed, "A")
    un = client.get("/v1/onus/unstable?days=30&min_drops=3", headers=h).json()
    mine = [i for i in un["items"] if i["serial"] in (flappy, calm)]
    assert [i["serial"] for i in mine] == [flappy] and mine[0]["drops"] == 4 and mine[0]["olt"] == olt
    assert not [i for i in client.get("/v1/onus/unstable?days=30&min_drops=5", headers=h).json()["items"] if i["serial"] == flappy]
    rep = client.get("/v1/onus/offline?min_hours=24&include_stale=true", headers=h).json()["items"]
    row = next(i for i in rep if i["serial"] == flappy)
    assert row["drops_30d"] == 4 and abs(row["offline_hours_30d"] - (4 * 0 + 24 * 3 + 48)) < 0.3 and "calm" not in row["serial"].lower()
    csv = client.get("/v1/onus/offline?min_hours=24&include_stale=true&format=csv", headers=h).text
    assert csv.splitlines()[0].endswith("drops_30d,offline_hours_30d") and flappy in csv


def test_history_is_isolated_and_permissioned(client, seed, inv, olt):
    s = f"ISO{uuid4().hex[:8].upper()}"
    _push(client, inv, olt, s, "online", 3600)
    oid = _onu(client, seed, s)
    assert client.get(f"/v1/onus/{oid}/history", headers=hdr(client, "bob", seed, "B")).status_code == 404
    assert client.get("/v1/onus/unstable?min_drops=1", headers=hdr(client, "bob", seed, "B")).json()["items"] == []
    assert client.get(f"/v1/onus/{oid}/history", headers=hdr(client, "dave", seed, "A")).status_code == 200        # noc_n1 reads the inventory
    assert client.get(f"/v1/onus/{oid}/history", headers={**hdr(client, "carol", seed, "A")}).status_code == 403    # an auditor does not
    assert client.get(f"/v1/onus/{uuid4()}/history", headers=hdr(client, "alice", seed, "A")).status_code == 404
    assert client.get(f"/v1/onus/{oid}/history?days=0", headers=hdr(client, "alice", seed, "A")).status_code == 422


def test_history_cannot_be_written_through_the_application_role(client, seed, inv, olt, migrated):
    s = f"RO{uuid4().hex[:8].upper()}"
    _push(client, inv, olt, s, "online", 3600)
    for stmt in ("INSERT INTO onu_state_events (tenant_id, onu_id, olt_id, serial, from_status, to_status, at) SELECT tenant_id, id, olt_id, serial, NULL, 'offline', now() FROM onus LIMIT 1",
                 "UPDATE onu_state_events SET to_status = 'online'", "DELETE FROM onu_state_events"):
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text("SET LOCAL ROLE fibercore_app"))
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(stmt))
    with migrated.connect() as c:   # and the trigger (SECURITY DEFINER) still wrote on behalf of the ingest
        assert c.execute(text("SELECT count(*) FROM onu_state_events WHERE serial = :s"), {"s": s}).scalar_one() == 1


def test_equal_times_keep_the_applied_order_and_time_never_goes_back(client, seed, inv, olt, migrated):
    s = f"TIE{uuid4().hex[:8].upper()}"
    _timeline(client, inv, olt, s, [("online", 3 * DAY), ("offline", 2 * DAY), ("online", 2 * DAY), ("offline", 2 * DAY)])   # three changes at the same instant
    oid = _onu(client, seed, s)
    ev = client.get(f"/v1/onus/{oid}/history", headers=hdr(client, "alice", seed, "A")).json()["events"]
    chain = [(e["from"], e["to"]) for e in reversed(ev)]
    assert chain == [(None, "online"), ("online", "offline"), ("offline", "online"), ("online", "offline")]   # the applied order, not a guess among equals
    ats = [e["at"] for e in reversed(ev)]
    assert ats == sorted(ats)
    with migrated.begin() as c:   # a later change can never be stamped before the previous one, whatever the snapshot's clock says
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE onus SET status = 'online', observed_at = observed_at - interval '1 day' WHERE id = :i"), {"i": oid})
        last = c.execute(text("SELECT at, (SELECT max(at) FROM onu_state_events WHERE onu_id = :i AND seq < e.seq) AS before FROM onu_state_events e "
                              "WHERE onu_id = :i ORDER BY seq DESC LIMIT 1"), {"i": oid}).one()
    assert last.at >= last.before


def test_unstable_is_ranked_and_filtered_in_sql(client, seed, inv, olt, migrated):
    many, few = f"MANY{uuid4().hex[:6].upper()}", f"FEW{uuid4().hex[:6].upper()}"
    steps = [("online", 9 * DAY), ("offline", 8 * DAY), ("online", 7 * DAY), ("offline", 6 * DAY), ("online", 5 * DAY), ("offline", 4 * DAY)]
    for status, ago in steps:
        body = snap(inv, name=olt, observed=_now(-ago), onus=[{"serial": many, "pon_path": "0/1/0", "status": status},
                                                              {"serial": few, "pon_path": "0/1/0", "status": status if ago > 6 * DAY else "online"}])
        assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    h = hdr(client, "alice", seed, "A")
    with migrated.connect() as c:
        olt_id = c.execute(text("SELECT id FROM olts WHERE name = :n"), {"n": olt}).scalar_one()
    items = client.get("/v1/onus/unstable?min_drops=1&limit=1000", headers=h).json()["items"]
    mine = [i["serial"] for i in items if i["serial"] in (many, few)]
    assert mine == [many, few]          # more drops first
    one = client.get("/v1/onus/unstable?min_drops=1&limit=1", headers=h).json()
    assert one["count"] == 1 and one["truncated"] is True
    assert [i["serial"] for i in client.get(f"/v1/onus/unstable?min_drops=1&olt_id={olt_id}", headers=h).json()["items"]] == [many, few]
    assert client.get(f"/v1/onus/unstable?min_drops=1&olt_id={uuid4()}", headers=h).json()["items"] == []


def test_retention_keeps_the_state_each_window_starts_in(client, seed, inv, olt, migrated):
    s = f"RET{uuid4().hex[:8].upper()}"
    _timeline(client, inv, olt, s, [("online", 5 * DAY), ("offline", 4 * DAY)])
    oid = _onu(client, seed, s)
    with migrated.begin() as c:
        c.execute(text("UPDATE onu_state_events SET at = now() - interval '600 days' WHERE onu_id = :i AND from_status IS NULL"), {"i": oid})
        c.execute(text("INSERT INTO onu_state_events (tenant_id, onu_id, olt_id, serial, from_status, to_status, at) "
                       "SELECT tenant_id, id, olt_id, serial, 'online', 'offline', now() - interval '500 days' FROM onus WHERE id = :i"), {"i": oid})
    with pytest.raises(DBAPIError), migrated.begin() as c:   # a retention shorter than the longest query window is refused
        c.execute(text("SELECT onu_state_events_prune(30)"))
    with pytest.raises(DBAPIError), migrated.begin() as c:   # and the application role cannot run it at all
        c.execute(text("SET LOCAL ROLE fibercore_app"))
        c.execute(text("SELECT onu_state_events_prune(400)"))
    with migrated.begin() as c:
        c.execute(text("SELECT onu_state_events_prune(370)"))
        left = c.execute(text("SELECT count(*) FROM onu_state_events WHERE onu_id = :i"), {"i": oid}).scalar_one()
    assert left == 2   # the recent event plus the one just before the cut-off (the state the window starts in); the 600-day one is gone
