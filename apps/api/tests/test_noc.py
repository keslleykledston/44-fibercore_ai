from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from tests.conftest import agent, hdr, login, snap


def _now(delta_s=0):
    return (datetime.now(UTC) + timedelta(seconds=delta_s)).isoformat()


def onus(n, status, prefix, pon="0/1/0"):
    return [{"serial": f"{prefix}{i:03d}", "pon_path": pon, "status": status} for i in range(n)]


def incidents(client, headers, status=None):
    q = f"?status={status}" if status else ""
    return client.get(f"/v1/incidents{q}", headers=headers).json()


def push(client, inv, name, items, observed=None, complete=True):
    return client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"),
                       json=snap(inv, name=name, observed=observed or _now(), onus=items,
                                 pons=[{"pon_path": "0/1/0", "status": "up", "complete": complete}, {"pon_path": "0/1/1", "status": "up", "complete": complete}]))


def mine(client, h, olt):
    return [i for i in incidents(client, h)["incidents"] if i["olt"] == olt]


def up(prefix, n, pon="0/1/0"):
    return onus(n, "online", prefix, pon)


def test_mass_outage_opens_once_dedupes_and_resolves_with_hysteresis(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    assert push(client, inv, "OLT-N1", up("N1A", 10), observed=_now(-600)).status_code == 202   # healthy baseline
    assert mine(client, h, "OLT-N1") == []
    # 9 of the 10 ONUs seen online now drop together => open
    drop = up("N1A", 1) + [{"serial": f"N1A{i:03d}", "pon_path": "0/1/0", "status": "los"} for i in range(1, 10)]
    push(client, inv, "OLT-N1", drop, observed=_now(-540))
    inc = mine(client, h, "OLT-N1")
    assert len(inc) == 1 and inc[0]["status"] == "open" and inc[0]["suspected_cause"] == "fiber_or_los"
    assert inc[0]["evidence"]["onus_down"] == 9 and inc[0]["evidence"]["ratio"] == 0.9 and inc[0]["evidence"]["members"] == 9
    # same condition again: still ONE open incident (dedupe)
    push(client, inv, "OLT-N1", [{"serial": f"N1A{i:03d}", "pon_path": "0/1/0", "status": "los"} for i in range(10)], observed=_now(-480))
    assert len(mine(client, h, "OLT-N1")) == 1
    # partial recovery (7 of the 9 covered ONUs still down, between thresholds) => stays open (hysteresis)
    mixed = [{"serial": f"N1A{i:03d}", "pon_path": "0/1/0", "status": "online" if i < 3 else "los"} for i in range(10)]
    push(client, inv, "OLT-N1", mixed, observed=_now(-420))
    assert mine(client, h, "OLT-N1")[0]["status"] == "open"
    # full recovery => resolved
    push(client, inv, "OLT-N1", up("N1A", 10), observed=_now(-360))
    inc = mine(client, h, "OLT-N1")
    assert len(inc) == 1 and inc[0]["status"] == "resolved" and inc[0]["resolved_at"]


def test_small_pon_and_partial_outage_do_not_open(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N2", up("N2A", 4), observed=_now(-600))
    push(client, inv, "OLT-N2", onus(4, "los", "N2A"), observed=_now(-540))     # 4 dropped: below MIN_DROPPED
    push(client, inv, "OLT-N2B", up("N2B", 10), observed=_now(-600))
    push(client, inv, "OLT-N2B", up("N2B", 5) + [{"serial": f"N2B{i:03d}", "pon_path": "0/1/0", "status": "los"} for i in range(5, 10)],
         observed=_now(-540))                                                   # 5 of 10 dropped: 50%
    assert mine(client, h, "OLT-N2") == [] and mine(client, h, "OLT-N2B") == []


def test_dying_gasp_majority_suggests_power(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N3", up("N3A", 10), observed=_now(-600))
    push(client, inv, "OLT-N3", up("N3A", 2) + [{"serial": f"N3A{i:03d}", "pon_path": "0/1/0", "status": "dying_gasp"} for i in range(2, 10)],
         observed=_now(-540))
    inc = mine(client, h, "OLT-N3")
    assert inc and inc[0]["suspected_cause"] == "power"


def test_stale_snapshot_data_does_not_count_toward_current_state(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N4", up("N4A", 10), observed=_now(-600))
    push(client, inv, "OLT-N4", onus(10, "los", "N4A"), observed=_now(-540))     # opens
    assert len(mine(client, h, "OLT-N4")) == 1
    # a snapshot that only reports 2 healthy ONUs: the other 8 are NOT from this snapshot -> must not resolve
    push(client, inv, "OLT-N4", up("N4A", 2), observed=_now(-480))
    assert mine(client, h, "OLT-N4")[0]["status"] == "open"


def drop_pair(client, inv, name, prefix):
    push(client, inv, name, up(prefix, 10), observed=_now(-600))
    push(client, inv, name, onus(10, "los", prefix), observed=_now(-540))


def test_silent_edge_flags_incidents_and_never_fabricates_offline(client, seed, inv, migrated):
    h = hdr(client, "alice", seed, "A")
    drop_pair(client, inv, "OLT-N5", "N5A")
    client.post("/v1/edge/heartbeat", headers=agent(client, inv, "a1"),
                json={"edge_id": str(inv["a1"]["edge"]), "tenant_id": str(seed["A"]), "version": "x", "sent_at": _now()})
    assert mine(client, h, "OLT-N5")[0]["edge_silent"] is False
    with migrated.begin() as c:
        c.execute(text("UPDATE edges SET last_heartbeat_at = now() - interval '10 minutes' WHERE id=:i"), {"i": inv["a1"]["edge"]})
    data = incidents(client, h)
    assert mine(client, h, "OLT-N5")[0]["edge_silent"] is True and mine(client, h, "OLT-N5")[0]["status"] == "open"
    assert any(a["kind"] == "edge_silent" and a["edge"] == "inv-a1" for a in data["alerts"])
    onu = client.get("/v1/onus?serial=N5A000", headers=h).json()[0]
    assert onu["status"] == "los"  # last-known state preserved; silence did not rewrite it


def test_rbac_ack_and_tenant_isolation(client, seed, inv):
    ha = hdr(client, "alice", seed, "A")
    drop_pair(client, inv, "OLT-N6", "N6A")
    inc = mine(client, ha, "OLT-N6")[0]
    assert client.get("/v1/incidents", headers=hdr(client, "dave", seed, "A")).status_code == 200  # noc_n1 reads
    assert client.post(f"/v1/incidents/{inc['id']}/ack", headers=hdr(client, "dave", seed, "A")).status_code == 403  # but cannot ack
    assert client.get("/v1/incidents", headers={**login(client, "carol"), "X-Workspace-ID": str(seed["A"])}).status_code == 403  # auditor
    hb = hdr(client, "bob", seed, "B")
    assert incidents(client, hb) == {"incidents": [], "alerts": []}
    assert client.post(f"/v1/incidents/{inc['id']}/ack", headers=hb).status_code == 404
    assert client.post(f"/v1/incidents/{inc['id']}/ack", headers=ha).status_code == 200
    assert client.post(f"/v1/incidents/{inc['id']}/ack", headers=ha).status_code == 409
    assert mine(client, ha, "OLT-N6")[0]["acknowledged"] is True


def test_events_emitted_for_open_and_resolve(client, seed, inv, migrated):
    drop_pair(client, inv, "OLT-N7", "N7A")
    push(client, inv, "OLT-N7", up("N7A", 10), observed=_now(-480))
    with migrated.connect() as c:
        types = {r[0] for r in c.execute(text("SELECT event_type FROM events_outbox WHERE tenant_id=:t"), {"t": seed["A"]})}
    assert {"incident.opened", "incident.resolved"} <= types


def test_same_timestamp_resend_with_omitted_onus_does_not_reuse_old_states(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    ts = _now(-30)
    push(client, inv, "OLT-N8", up("N8A", 10), observed=ts)
    # resend with the SAME observed_at, reporting only 2 ONUs (both down): old states of the other 8 must not count
    push(client, inv, "OLT-N8", onus(2, "los", "N8A"), observed=ts)
    assert mine(client, h, "OLT-N8") == []


def test_concurrent_first_ingest_of_new_olt_has_no_500(client, seed, inv):
    import threading
    codes = []
    ts = [threading.Thread(target=lambda: codes.append(push(client, inv, "OLT-N9", up("N9A", 10), observed=_now(-600)).status_code))
          for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert 500 not in codes and codes.count(202) >= 1, codes


def test_concurrent_drop_snapshots_open_a_single_incident(client, seed, inv):
    import threading
    push(client, inv, "OLT-N9B", up("N9B", 10), observed=_now(-600))
    codes = []
    when = _now(-540)
    ts = [threading.Thread(target=lambda: codes.append(push(client, inv, "OLT-N9B", onus(10, "los", "N9B"), observed=when).status_code))
          for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert 500 not in codes, codes
    assert len(mine(client, hdr(client, "alice", seed, "A"), "OLT-N9B")) == 1


def test_partial_sample_never_opens_incident(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N10", up("N10A", 6), observed=_now(-600))
    push(client, inv, "OLT-N10", onus(6, "los", "N10A"), observed=_now(-540), complete=False)   # all drop, but PON not fully read
    assert mine(client, h, "OLT-N10") == []
    push(client, inv, "OLT-N10", onus(6, "los", "N10A"), observed=_now(-480), complete=True)    # same data declared complete
    assert len(mine(client, h, "OLT-N10")) == 1


# ---- the reason for the redesign: a measured MA5608T had 37% of its ONTs offline for months -------------------------------

def test_chronically_offline_fleet_never_opens_an_incident(client, seed, inv):
    """Shapes taken from a real OLT: 38 ONTs / 5 online (0/0/9) and 6 ONTs / 1 online (0/1/5). Seen offline from the first
    snapshot on, they are chronic: no incident now, none on later snapshots, none after the drop window has passed."""
    h = hdr(client, "alice", seed, "A")
    fleet = up("C1O", 5) + onus(33, "offline", "C1X")
    small = up("C2O", 1) + onus(5, "offline", "C2X")
    for t in (-3600, -3000, -1000, -10):
        push(client, inv, "OLT-C1", fleet, observed=_now(t))
        push(client, inv, "OLT-C2", small, observed=_now(t))
    assert mine(client, h, "OLT-C1") == [] and mine(client, h, "OLT-C2") == []


def test_first_observation_of_a_down_fleet_opens_nothing(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-C3", onus(10, "los", "C3A"), observed=_now(-60))
    assert mine(client, h, "OLT-C3") == []   # no prior observation: cannot tell an outage from a long-dead fleet


def test_chronic_offline_do_not_dilute_a_real_drop_and_are_reported(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    chronic = onus(30, "offline", "C4X")
    push(client, inv, "OLT-C4", up("C4O", 10) + chronic, observed=_now(-600))
    push(client, inv, "OLT-C4", onus(10, "offline", "C4O") + chronic, observed=_now(-540))
    inc = mine(client, h, "OLT-C4")
    assert len(inc) == 1 and inc[0]["evidence"]["onus_down"] == 10 and inc[0]["evidence"]["ratio"] == 1.0
    assert inc[0]["evidence"]["chronic_offline"] == 30 and inc[0]["suspected_cause"] == "unknown"


def test_incident_survives_the_drop_window_and_resolves_when_its_onus_return(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-C5", up("C5A", 10), observed=_now(-4000))
    push(client, inv, "OLT-C5", onus(10, "los", "C5A"), observed=_now(-3800))
    assert mine(client, h, "OLT-C5")[0]["status"] == "open"
    push(client, inv, "OLT-C5", onus(10, "los", "C5A"), observed=_now(-100))   # >30 min later, all still down
    assert mine(client, h, "OLT-C5")[0]["status"] == "open"                    # the window expiring must NOT resolve it
    push(client, inv, "OLT-C5", up("C5A", 10), observed=_now(-50))
    assert mine(client, h, "OLT-C5")[0]["status"] == "resolved"


def test_outage_while_the_edge_was_silent_is_still_detected(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-C6", up("C6A", 10), observed=_now(-7200))           # last healthy view two hours ago
    push(client, inv, "OLT-C6", onus(10, "los", "C6A"), observed=_now(-10))    # first snapshot after the silence: all down
    assert len(mine(client, h, "OLT-C6")) == 1


def test_onus_dropping_after_the_incident_opened_join_it(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-C7", up("C7A", 12), observed=_now(-600))
    ten_down = onus(10, "los", "C7A") + [{"serial": f"C7A{i:03d}", "pon_path": "0/1/0", "status": "online"} for i in (10, 11)]
    push(client, inv, "OLT-C7", ten_down, observed=_now(-540))                 # 10 of 12 => opens with 10 members
    assert mine(client, h, "OLT-C7")[0]["evidence"]["members"] == 10
    push(client, inv, "OLT-C7", onus(12, "los", "C7A"), observed=_now(-480))   # the last two drop too: they join the incident
    inc = mine(client, h, "OLT-C7")
    assert len(inc) == 1 and inc[0]["evidence"]["members"] == 12 and inc[0]["evidence"]["onus_down"] == 12


def test_incident_without_membership_rows_is_adopted_not_orphaned(client, seed, inv, migrated):
    h = hdr(client, "alice", seed, "A")
    drop_pair(client, inv, "OLT-C8", "C8A")
    with migrated.begin() as c:                                                 # simulate an incident opened before membership existed
        c.execute(text("DELETE FROM incident_onus"))
    push(client, inv, "OLT-C8", up("C8A", 10), observed=_now(-480))
    assert mine(client, h, "OLT-C8")[0]["status"] == "resolved"


def test_snapshot_ties_cannot_fabricate_or_erase_a_drop(client, seed, inv):
    """Same observed_at = a retry of the snapshot already applied. Reordering ties must not create or remove a drop."""
    h = hdr(client, "alice", seed, "A")
    tie = _now(-540)
    push(client, inv, "OLT-T1", up("T1A", 10), observed=_now(-600))
    push(client, inv, "OLT-T1", up("T1A", 10), observed=tie)                 # healthy at the tie timestamp
    push(client, inv, "OLT-T1", onus(10, "los", "T1A"), observed=tie)        # a different payload replayed at the SAME instant
    assert mine(client, h, "OLT-T1") == []                                   # must not fabricate a drop
    push(client, inv, "OLT-T2", up("T2A", 10), observed=_now(-600))
    push(client, inv, "OLT-T2", onus(10, "los", "T2A"), observed=tie)        # real drop applied
    assert len(mine(client, h, "OLT-T2")) == 1
    push(client, inv, "OLT-T2", up("T2A", 10), observed=tie)                 # a tied "healthy" replay must not erase it
    assert mine(client, h, "OLT-T2")[0]["status"] == "open"
    onu = client.get("/v1/onus?serial=T2A000", headers=h).json()[0]
    assert onu["status"] == "los"
