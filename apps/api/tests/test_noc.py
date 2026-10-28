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


def test_mass_outage_opens_once_dedupes_and_resolves_with_hysteresis(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    assert push(client, inv, "OLT-N1", onus(10, "online", "N1A")).status_code == 202
    assert mine(client, h, "OLT-N1") == []
    # 9/10 down => open
    push(client, inv, "OLT-N1", onus(1, "online", "N1A") + [{**o, "serial": o["serial"].replace("N1A", "N1B")} for o in onus(9, "los", "N1A")][:0]
         + [{"serial": f"N1A{i:03d}", "pon_path": "0/1/0", "status": "los"} for i in range(1, 10)], observed=_now(5))
    inc = mine(client, h, "OLT-N1")
    assert len(inc) == 1 and inc[0]["status"] == "open" and inc[0]["suspected_cause"] == "fiber_or_los"
    assert inc[0]["evidence"]["onus_down"] == 9 and inc[0]["evidence"]["ratio"] == 0.9
    # same condition again: still ONE open incident (dedupe)
    push(client, inv, "OLT-N1", [{"serial": f"N1A{i:03d}", "pon_path": "0/1/0", "status": "los"} for i in range(10)], observed=_now(10))
    assert len(mine(client, h, "OLT-N1")) == 1
    # partial recovery to 70% down (between thresholds) => stays open (hysteresis)
    mixed = [{"serial": f"N1A{i:03d}", "pon_path": "0/1/0", "status": "online" if i < 3 else "los"} for i in range(10)]
    push(client, inv, "OLT-N1", mixed, observed=_now(15))
    assert mine(client, h, "OLT-N1")[0]["status"] == "open"
    # full recovery => resolved
    push(client, inv, "OLT-N1", onus(10, "online", "N1A"), observed=_now(20))
    inc = mine(client, h, "OLT-N1")
    assert len(inc) == 1 and inc[0]["status"] == "resolved" and inc[0]["resolved_at"]


def test_small_pon_and_partial_outage_do_not_open(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N2", onus(4, "los", "N2A"))                      # 4 ONUs: below MIN_ONUS
    push(client, inv, "OLT-N2", onus(10, "online", "N2B")[:5] + onus(5, "los", "N2C"), observed=_now(5))  # 50% down
    assert mine(client, h, "OLT-N2") == []


def test_dying_gasp_majority_suggests_power(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N3", onus(8, "dying_gasp", "N3A") + onus(2, "online", "N3B"))
    inc = mine(client, h, "OLT-N3")
    assert inc and inc[0]["suspected_cause"] == "power"


def test_stale_snapshot_data_does_not_count_toward_current_state(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N4", onus(10, "los", "N4A"))          # opens
    assert len(mine(client, h, "OLT-N4")) == 1
    # a snapshot that only reports 2 healthy ONUs: the other 8 are NOT from this snapshot -> must not resolve nor reopen
    push(client, inv, "OLT-N4", onus(2, "online", "N4A"), observed=_now(5))
    assert mine(client, h, "OLT-N4")[0]["status"] == "open"


def test_silent_edge_flags_incidents_and_never_fabricates_offline(client, seed, inv, migrated):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N5", onus(10, "los", "N5A"))
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
    push(client, inv, "OLT-N6", onus(10, "los", "N6A"))
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
    push(client, inv, "OLT-N7", onus(10, "los", "N7A"))
    push(client, inv, "OLT-N7", onus(10, "online", "N7A"), observed=_now(5))
    with migrated.connect() as c:
        types = {r[0] for r in c.execute(text("SELECT event_type FROM events_outbox WHERE tenant_id=:t"), {"t": seed["A"]})}
    assert {"incident.opened", "incident.resolved"} <= types


def test_same_timestamp_resend_with_omitted_onus_does_not_reuse_old_states(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    ts = _now(-30)
    push(client, inv, "OLT-N8", onus(10, "online", "N8A"), observed=ts)
    # resend with the SAME observed_at, reporting only 2 ONUs (both down): old states of the other 8 must not count
    push(client, inv, "OLT-N8", onus(2, "los", "N8A"), observed=ts)
    assert mine(client, h, "OLT-N8") == []


def test_concurrent_first_ingest_of_new_olt_has_no_500_and_single_incident(client, seed, inv):
    import threading
    codes = []

    def go():
        codes.append(push(client, inv, "OLT-N9", onus(10, "los", "N9A")).status_code)

    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert 500 not in codes and codes.count(202) >= 1, codes
    assert len(mine(client, hdr(client, "alice", seed, "A"), "OLT-N9")) == 1


def test_partial_sample_never_opens_incident(client, seed, inv):
    h = hdr(client, "alice", seed, "A")
    push(client, inv, "OLT-N10", onus(20, "online", "N10A"))                                  # known: 20 healthy ONUs
    push(client, inv, "OLT-N10", onus(6, "los", "N10B"), observed=_now(5), complete=False)    # 6 reported down, PON not fully read
    assert mine(client, h, "OLT-N10") == []
    push(client, inv, "OLT-N10", onus(6, "los", "N10B"), observed=_now(10), complete=True)    # same data but declared complete
    assert len(mine(client, h, "OLT-N10")) == 1
