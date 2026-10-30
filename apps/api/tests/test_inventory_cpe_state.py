"""CPE state from the ACS cache (SD-001 / ADR-SD-002): closed metric list, typed values, per-edge ownership, newest device time wins, RLS."""
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.cpe_state import METRICS
from tests.conftest import _now, agent, hdr

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True, scope="module")
def _clean_up_after_the_module(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'STATE%'"))  # cpe_state and bindings follow (ON DELETE CASCADE)


def _cpe(client, inv, serial, ext, key="a1"):
    body = {"edge_id": str(inv[key]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": serial, "vendor": "ACME", "model": "G3000",
         "binding": {"protocol": "tr069", "external_id": ext, "connector_id": f"c-st-{key}"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, key), json=body).status_code == 202


def _cpe_id(client, seed, serial, who="alice", tenant="A"):
    return next(c["id"] for c in client.get("/v1/cpes", headers=hdr(client, who, seed, tenant)).json() if c["canonical_serial"] == serial)


def _m(name, scope, value, at=None):
    return {"name": name, "scope": scope, "value": value, "captured_at": at or _now(-30)}


def _state(inv, ext, metrics, key="a1", observed=None):
    return {"edge_id": str(inv[key]["edge"]), "observed_at": observed or _now(), "states": [
        {"binding": {"protocol": "tr069", "external_id": ext, "connector_id": f"c-st-{key}"}, "metrics": metrics}]}


def _post(client, inv, body, key="a1"):
    return client.post("/v1/edge/cpe-state", headers=agent(client, inv, key), json=body)


def test_ingest_then_read_back_with_provenance_and_age(client, seed, inv):
    _cpe(client, inv, "STATE-0001", "st-1")
    metrics = [_m("wan_link_status", "link/1", "Up"), _m("wan_connection_status", "ppp/3/1", "Connected"), _m("uptime_seconds", "ppp/3/1", 5844),
               _m("wifi_radio_enabled", "radio/5", True), _m("wifi_channel", "radio/5", 36)]
    r = _post(client, inv, _state(inv, "st-1", metrics))
    assert r.status_code == 202 and r.json() == {"status": "accepted", "cpes": 1, "metrics": 5, "unknown": 0}, r.text
    got = client.get(f"/v1/cpes/{_cpe_id(client, seed, 'STATE-0001')}/state", headers=hdr(client, "alice", seed, "A")).json()
    assert got["source"] == "acs_cache" and len(got["metrics"]) == 5
    by = {(m["metric"], m["scope"]): m for m in got["metrics"]}
    assert by[("wifi_radio_enabled", "radio/5")]["value"] is True and by[("wifi_channel", "radio/5")]["value"] == 36
    assert by[("wan_connection_status", "ppp/3/1")]["value"] == "Connected" and by[("uptime_seconds", "ppp/3/1")]["value"] == 5844
    assert all(m["fresh"] and 0 <= m["age_seconds"] < 300 and m["received_at"] for m in got["metrics"])


@pytest.mark.parametrize("bad", [
    _m("ssid", "radio/1", "MyHome"),                        # not a metric of the closed list
    _m("wan_link_status", "link/1", "up"),                  # not in the enum (case matters here: the Edge already normalised it)
    _m("wan_link_status", "link/1", "Connected"),           # an enum of ANOTHER metric
    _m("wifi_channel", "radio/1", True),                    # a bool is not an int
    _m("wifi_channel", "radio/1", 197),                     # out of range
    _m("wifi_channel", "radio/1", "11"),                    # a string is not an int
    _m("wifi_radio_enabled", "radio/1", 1),                 # an int is not a bool
    _m("uptime_seconds", "ppp/1/1", -1),
    _m("uptime_seconds", "ppp/1/1", (1 << 31) + 1),
    _m("wan_link_status", "Link/1", "Up"),                  # the scope is closed per metric: fixed word + numeric instances
    _m("wan_link_status", "link/one", "Up"),
    _m("wan_link_status", "link/1/AA:BB:CC:DD:EE:FF", "Up"),  # a MAC cannot ride in the scope
    _m("wan_link_status", "myhome/1", "Up"),                # nor an SSID that merely looks like word/number
    _m("wifi_channel", "myhome/1", 6),
    _m("wifi_channel", "link/1", 6),                        # a scope of ANOTHER metric
    _m("wan_connection_status", "radio/1", "Connected"),
    _m("wan_connection_status", "ppp/1/2/3", "Connected"),  # at most two instance numbers
    _m("uptime_seconds", "radio/1", 5),
    _m("wifi_radio_enabled", "radio/1234", True),           # at most three digits per instance
    _m("wan_link_status", "link/1", "Up", at="2999-01-01T00:00:00+00:00"),  # device clock in the future
    _m("wan_link_status", "link/1", "Up", at="2026-10-29T12:00:00"),        # no timezone
    {**_m("wan_link_status", "link/1", "Up"), "ssid": "MyHome"},            # unknown field (strict body)
])
def test_closed_list_typed_values_and_scope_are_enforced(client, inv, bad):
    _cpe(client, inv, "STATE-0002", "st-2")
    assert _post(client, inv, _state(inv, "st-2", [bad])).status_code == 422
    body = _state(inv, "st-2", [_m("wan_link_status", "link/1", "Up")])
    body["states"][0]["psk"] = "x"  # no extra keys anywhere in the envelope either
    assert _post(client, inv, body).status_code == 422
    assert _post(client, inv, _state(inv, "st-2", [])).status_code == 422  # a CPE entry with no metric is not a state
    assert _post(client, inv, _state(inv, "st-2", [_m("wifi_channel", "radio/1", 1)] * 65)).status_code == 422  # bounded per CPE


def test_edge_can_only_write_state_of_its_own_cpes_and_unknown_is_not_an_oracle(client, seed, inv):
    _cpe(client, inv, "STATE-0003", "st-3", key="a1")
    cid = _cpe_id(client, seed, "STATE-0003")
    ok = [_m("wan_link_status", "link/1", "Up")]
    # another edge of the SAME tenant names a1's CPE (same connector id the CPE was bound with): ignored, indistinguishable from unknown
    forged = _state(inv, "st-3", ok, key="a2")
    forged["states"][0]["binding"]["connector_id"] = "c-st-a1"
    assert _post(client, inv, forged, key="a2").json() == {"status": "accepted", "cpes": 0, "metrics": 0, "unknown": 1}
    # a binding that does not exist at all gives the same answer
    nothing = _state(inv, "does-not-exist", ok)
    assert _post(client, inv, nothing).json() == {"status": "accepted", "cpes": 0, "metrics": 0, "unknown": 1}
    # a token bound to a different edge cannot post for this edge
    assert _post(client, inv, _state(inv, "st-3", ok, key="a1"), key="a2").status_code == 403
    assert client.get(f"/v1/cpes/{cid}/state", headers=hdr(client, "alice", seed, "A")).json()["metrics"] == []


def test_only_a_strictly_newer_device_time_overwrites(client, seed, inv):
    _cpe(client, inv, "STATE-0004", "st-4")
    cid = _cpe_id(client, seed, "STATE-0004")
    h = hdr(client, "alice", seed, "A")
    read = lambda: {(m["metric"], m["scope"]): m["value"] for m in client.get(f"/v1/cpes/{cid}/state", headers=h).json()["metrics"]}  # noqa: E731
    t_old, t_mid, t_new = _now(-300), _now(-200), _now(-100)
    assert _post(client, inv, _state(inv, "st-4", [_m("wifi_channel", "radio/1", 6, t_mid)])).status_code == 202
    assert _post(client, inv, _state(inv, "st-4", [_m("wifi_channel", "radio/1", 1, t_old)])).status_code == 202  # older: ignored
    assert read() == {("wifi_channel", "radio/1"): 6}
    assert _post(client, inv, _state(inv, "st-4", [_m("wifi_channel", "radio/1", 11, t_mid)])).status_code == 202  # same time: a replay
    assert read() == {("wifi_channel", "radio/1"): 6}
    assert _post(client, inv, _state(inv, "st-4", [_m("wifi_channel", "radio/1", 11, t_new)])).status_code == 202  # newer: applied
    assert read() == {("wifi_channel", "radio/1"): 11}


def test_tenant_isolation_on_read_and_in_the_database(client, seed, inv, migrated):
    _cpe(client, inv, "STATE-0005", "st-5")
    cid = _cpe_id(client, seed, "STATE-0005")
    assert _post(client, inv, _state(inv, "st-5", [_m("wan_link_status", "link/1", "Up")])).status_code == 202
    assert client.get(f"/v1/cpes/{cid}/state", headers=hdr(client, "alice", seed, "A")).status_code == 200
    assert client.get(f"/v1/cpes/{cid}/state", headers=hdr(client, "bob", seed, "B")).status_code == 404  # tenant B cannot even see the CPE
    with migrated.begin() as c:  # row level security itself, not only the API filter
        c.execute(text("SET LOCAL ROLE fibercore_app"))
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
        assert c.execute(text("SELECT count(*) FROM cpe_state")).scalar() == 0
        with pytest.raises(DBAPIError):  # and a write under tenant B naming tenant A's CPE is refused
            c.execute(text("INSERT INTO cpe_state (tenant_id, cpe_id, metric, scope, value, captured_at, observed_at) "
                           "VALUES (:t, :c, 'wifi_channel', 'radio/1', '1', now(), now())"), {"t": str(seed["A"]), "c": cid})


def test_the_database_refuses_what_the_api_would_never_send(migrated, client, seed, inv):
    _cpe(client, inv, "STATE-0006", "st-6")
    cid = _cpe_id(client, seed, "STATE-0006")
    for metric, scope, value in [("ssid", "radio/1", '"x"'), ("wifi_channel", "Radio/1", "1"), ("wifi_channel", "radio/1/aa", "1"),
                                 ("wifi_channel", "myhome/1", "1"), ("wifi_channel", "link/1", "1"), ("wan_link_status", "radio/1", '"Up"'),
                                 ("wan_connection_status", "ppp/1/2/3", '"Up"'), ("uptime_seconds", "radio/1", "1"),
                                 ("wifi_channel", "radio/1", "null"), ("wifi_channel", "radio/1", '{"a":1}'), ("wifi_channel", "radio/1", "[1]")]:
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text("INSERT INTO cpe_state (tenant_id, cpe_id, metric, scope, value, captured_at, observed_at) "
                           "VALUES (:t, :c, :m, :s, CAST(:v AS jsonb), now(), now())"),
                      {"t": str(seed["A"]), "c": cid, "m": metric, "s": scope, "v": value})


def test_cloud_metric_table_matches_what_the_edge_emits():
    # agents/edge/internal/nbi/params.go is the only source of what is read; the cloud must accept every metric and enum it can produce
    src = (ROOT / "agents" / "edge" / "internal" / "nbi" / "params.go").read_text(encoding="utf-8")
    names = set(re.findall(r'metric: "([a-z_]+)"', src))
    assert names and names == set(METRICS), sorted(names ^ set(METRICS))
    emitted = {s for group in re.findall(r"set\(([^)]*)\)", src) for s in re.findall(r'"([A-Za-z]+)"', group)}
    cloud_enums = set().union(*(spec[1] for spec in METRICS.values() if spec[0] == "enum"))
    assert emitted == cloud_enums, sorted(emitted ^ cloud_enums)
    assert re.search(r"uptime\s+=\s*spec\{metric: \"uptime_seconds\", kind: kInt, min: 0, max: 1 << 31\}", src)
    assert re.search(r"channel\s+=\s*spec\{metric: \"wifi_channel\", kind: kInt, min: 0, max: 196\}", src)


def test_every_scope_the_edge_can_emit_is_accepted_by_the_api_and_by_the_database(migrated, client, seed, inv):
    _cpe(client, inv, "STATE-0007", "st-7")
    cid = _cpe_id(client, seed, "STATE-0007")
    good = [("wan_link_status", "link/1", "Up"), ("wan_connection_status", "ppp/3/1", "Connected"), ("wan_connection_status", "ip/2/1", "Connected"),
            ("wan_connection_status", "ppp/2", "Up"), ("uptime_seconds", "ppp/3/1", 1), ("uptime_seconds", "device/0", 1),
            ("wifi_radio_enabled", "radio/5", True), ("wifi_channel", "radio/8", 1)]
    r = _post(client, inv, _state(inv, "st-7", [_m(n, s, v) for n, s, v in good]))
    assert r.status_code == 202 and r.json()["metrics"] == len(good), r.text
    with migrated.begin() as c:  # the same scopes pass the CHECK on their own
        for n, s, _ in good:
            c.execute(text("INSERT INTO cpe_state (tenant_id, cpe_id, metric, scope, value, captured_at, observed_at) "
                           "VALUES (:t, :c, :m, :s, '1', now(), now()) ON CONFLICT DO NOTHING"), {"t": str(seed["A"]), "c": cid, "m": n, "s": s})


def test_cloud_scopes_are_the_ones_the_edge_tests_pin():
    # the Edge pins the same patterns in agents/edge/internal/nbi/params_test.go (cloudScopeByMetric); both sides must not drift
    from app.api.cpe_state import SCOPE_RE

    go = (ROOT / "agents" / "edge" / "internal" / "nbi" / "params_test.go").read_text(encoding="utf-8")
    block = go[go.index("var cloudScopeByMetric"):]
    block = block[:block.index("\n}\n")]
    pinned = dict(re.findall(r'"([a-z_]+)":\s*regexp\.MustCompile\(`([^`]+)`\)', block))
    assert set(pinned) == set(SCOPE_RE) == set(METRICS)
    assert all(pinned[k] == SCOPE_RE[k].pattern for k in pinned), {k: (pinned[k], SCOPE_RE[k].pattern) for k in pinned if pinned[k] != SCOPE_RE[k].pattern}
