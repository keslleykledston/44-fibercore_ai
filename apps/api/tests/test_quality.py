"""QoS-001 (ADR-0039), the pure part: metrics without false zeros, freshness, the honest global state and the declarative hypotheses. No database."""
from datetime import UTC, datetime, timedelta

import pytest

from app.core import quality as q

NOW = datetime(2026, 10, 31, 20, 0, 0, tzinfo=UTC)
ago = lambda s: NOW - timedelta(seconds=s)  # noqa: E731
row = lambda m, scope, v, age=60: q.StateRow(m, scope, v, ago(age))  # noqa: E731
FULL_STATE = (row("wan_link_status", "link/1", "Up"), row("wan_connection_status", "ppp/3/1", "Connected"), row("uptime_seconds", "ppp/3/1", 12345),
              row("wifi_radio_enabled", "radio/1", "Enabled"), row("wifi_channel", "radio/1", 6))


def build(**kw):
    f = q.Facts(now=NOW, **kw)
    ms = q.build_metrics(f)
    hs = q.hypotheses(ms, f)
    return f, ms, hs, q.summarize(ms, hs)


def one(ms, mid, instance=None):
    return next(m for m in ms if m["id"] == mid and (instance is None or m["instance"] == instance))


def test_Q16_nothing_available_is_insufficient_data_never_ok():
    _, ms, hs, s = build()
    assert s["state"] == "insufficient_data" and hs == [] and s["note"]
    assert all(m["value"] is None for m in ms) and all(m["status"] in ("not_available", "not_applicable") for m in ms)
    assert q.run_state(ms) == "partial"


def test_Q04_a_missing_reading_is_not_available_and_carries_no_number():
    _, ms, _, _ = build(cpe_state=(row("wan_link_status", "link/1", "Up"),))
    for mid in ("wifi.radio_enabled", "wifi.channel", "cpe.uptime_s"):
        m = one(ms, mid)
        assert m["status"] == "not_available" and m["value"] is None and m["details"]["reason"] == "no_reading"


def test_Q05_a_reading_older_than_its_ttl_is_stale_and_not_counted_as_current():
    _, ms, _, s = build(cpe_state=(row("wan_link_status", "link/1", "Down", age=q.TTL_S["WAN"] + 1), row("uptime_seconds", "device/0", 5, age=q.TTL_S["CPE"] + 1)))
    assert one(ms, "wan.link_status")["status"] == "stale" and one(ms, "wan.link_status")["value"] == "Down"   # shown as history, with its age
    assert q.observations(ms) == []                                                                          # a stale "Down" is not today's anomaly
    assert s["state"] == "insufficient_data" and s["indicators"]["wan"]["state"] == "stale"


def test_the_boundary_of_the_ttl_is_inclusive():
    for age, st in ((q.TTL_S["WAN"], "valid"), (q.TTL_S["WAN"] + 1, "stale")):
        _, ms, _, _ = build(cpe_state=(row("wan_link_status", "link/1", "Up", age=age),))
        assert one(ms, "wan.link_status")["status"] == st


def test_Q03_a_wan_reading_is_never_attributed_to_the_subscriber_service():
    _, ms, _, _ = build(cpe_state=FULL_STATE)
    wan = [m for m in ms if m["group"] == "WAN"]
    assert wan and all(m["scope"] == "WAN_UNCLASSIFIED" and m["source"] == "ACS_CACHE" for m in wan)
    assert not any(m["scope"] in ("SERVICE_WAN",) for m in ms)


def test_Q12_the_optical_level_comes_from_the_olt_and_is_judged_only_with_a_homologated_profile():
    onu = q.OnuFact("online", -27.5, ago(120))
    _, ms, hs, _ = build(onu=onu)
    rx = one(ms, "optical.rx_dbm")
    assert rx["source"] == "OLT_ADAPTER" and rx["scope"] == "PON" and rx["unit"] == "dBm" and rx["value"] == -27.5 and rx["details"]["judged"] is False
    assert hs == []                                                       # no generic dBm limit exists: no profile, no judgement
    _, _, hs, s = build(onu=onu, optical_profile=(-27.0, -8.0))
    assert [h["code"] for h in hs] == ["OPTICAL_ATTENTION"] and hs[0]["evidence_metric_ids"] == ["optical.rx_dbm"] and hs[0]["caveats"] and s["state"] == "attention"
    _, _, hs, _ = build(onu=q.OnuFact("online", -20.0, ago(120)), optical_profile=(-27.0, -8.0))
    assert hs == []
    _, _, hs, _ = build(onu=q.OnuFact("online", -30.0, ago(q.TTL_S["OPTICAL"] + 5)), optical_profile=(-27.0, -8.0))
    assert hs == []                                                       # an old reading never raises a hypothesis


def test_an_onu_that_is_not_linked_says_so_instead_of_inventing_an_optical_level():
    _, ms, _, _ = build(cpe_state=FULL_STATE)
    assert one(ms, "optical.rx_dbm")["details"]["reason"] == "no_linked_onu" and one(ms, "onu.status")["value"] is None


def test_observed_anomalies_make_attention_without_any_hypothesis():
    _, ms, hs, s = build(cpe_state=(row("wan_link_status", "link/1", "Down"), row("wan_connection_status", "ppp/3/1", "Disconnected")),
                         onu=q.OnuFact("offline", None, ago(60)))
    assert hs == [] and s["state"] == "attention"
    assert {o["code"] for o in s["observations"]} == {"WAN_LINK_DOWN", "WAN_CONNECTION_NOT_UP", "ONU_NOT_ONLINE"}
    assert s["indicators"]["wan"]["state"] == "attention" and s["indicators"]["optical"]["state"] == "attention"


def test_enough_current_data_without_an_anomaly_is_no_anomalies_observed_never_perfect():
    _, ms, hs, s = build(cpe_state=FULL_STATE, onu=q.OnuFact("online", -18.0, ago(300)))
    assert hs == [] and s["state"] == "no_anomalies_observed" and s["note"]
    assert s["indicators"]["wan"]["state"] == s["indicators"]["optical"]["state"] == "ok"


def test_one_current_group_is_not_enough_to_say_anything_good():
    _, _, _, s = build(cpe_state=(row("wan_link_status", "link/1", "Up"),))
    assert s["state"] == "insufficient_data"


def test_an_unknown_onu_status_is_not_an_anomaly():
    _, _, _, s = build(onu=q.OnuFact("unknown", -10.0, ago(10)))
    assert s["observations"] == []


def test_the_contract_never_keeps_a_value_for_a_state_that_is_not_a_reading():
    for st in ("not_supported", "not_available", "not_applicable", "failed", "inconclusive"):
        assert q.metric("x.y", "WAN", st, value=0, source="ACS_CACHE", scope="WAN_UNCLASSIFIED", now=NOW)["value"] is None
    assert q.metric("x.y", "WAN", "valid", value=0, source="ACS_CACHE", scope="WAN_UNCLASSIFIED", now=NOW)["value"] == 0
    with pytest.raises(AssertionError):
        q.metric("x.y", "WAN", "great", source="ACS_CACHE", scope="WAN_UNCLASSIFIED", now=NOW)
    with pytest.raises(AssertionError):
        q.metric("x.y", "WAN", "valid", source="TR069", scope="WAN_UNCLASSIFIED", now=NOW)   # "TR069" alone is not a source: the optical level must never wear it


def test_the_same_facts_give_the_same_answer():
    f = q.Facts(now=NOW, cpe_state=FULL_STATE, onu=q.OnuFact("online", -20.0, ago(10)))
    assert q.build_metrics(f) == q.build_metrics(f) and q.summarize(q.build_metrics(f), []) == q.summarize(q.build_metrics(f), [])


# ---- the rules that need more than the passive data (they stay dormant until their inputs exist) ------------------------------------------------------
def ex(mid, group, value, unit=None, **details):
    return q.metric(mid, group, "valid", value=value, unit=unit, source="TR069_ACTIVE", scope="LAN", now=NOW, collected_at=ago(5), details=details)


def codes(**kw):
    f = q.Facts(now=NOW, **{k: v for k, v in kw.items() if k != "metrics"})
    return [h["code"] for h in q.hypotheses(list(kw.get("metrics", ())), f)]


def test_Q11_a_100m_lan_link_is_a_hypothesis_only_against_a_known_faster_plan():
    m = [ex("eth.link_speed_mbps", "ETHERNET", 100, "Mbit/s")]
    assert codes(metrics=m) == [] and codes(metrics=m, plan_mbps=100) == []
    assert codes(metrics=m, plan_mbps=500) == ["LAN_LINK_100M"]
    assert codes(metrics=[ex("eth.link_speed_mbps", "ETHERNET", 1000)], plan_mbps=500) == []


def test_wifi_needs_a_homologated_profile_and_both_signals():
    m = [ex("wifi.rssi_dbm", "WIFI", -80, "dBm"), ex("wifi.retry_pct", "WIFI", 40, "%")]
    assert codes(metrics=m) == [] and codes(metrics=m, wifi_profile=(-70.0, 20.0)) == ["WIFI_POTENTIAL"]
    assert codes(metrics=m[:1], wifi_profile=(-70.0, 20.0)) == []
    assert codes(metrics=[ex("wifi.rssi_dbm", "WIFI", -60, "dBm"), m[1]], wifi_profile=(-70.0, 20.0)) == []


def sp(direction, kind, mbps, outcome="completed"):
    return q.SpeedFact("r1", "g1", direction, kind, outcome, mbps, ago(60))


def test_Q17_core_good_internet_bad_is_only_a_potential_external_path():
    _, ms, hs, _ = build(speed=(sp("download", "CORE", 400.0), sp("download", "INTERNET", 100.0)))
    assert [h["code"] for h in hs] == ["EXTERNAL_PATH_POTENTIAL"] and "servidor" in hs[0]["caveats"][0] and hs[0]["confidence"] == "low"
    assert {m["source"] for m in ms if m["group"] in ("CORE", "INTERNET")} == {"SD001"}
    assert all(m["evidence_ref"].startswith("speed-run:") for m in ms if m["group"] in ("CORE", "INTERNET"))


def test_both_paths_degraded_against_a_known_plan_point_at_the_access_path():
    _, _, hs, _ = build(speed=(sp("download", "CORE", 100.0), sp("download", "INTERNET", 90.0)), plan_mbps=500)
    assert [h["code"] for h in hs] == ["ACCESS_PATH_POTENTIAL"]
    _, _, hs, _ = build(speed=(sp("download", "CORE", 100.0), sp("download", "INTERNET", 90.0)))
    assert hs == []                                                         # without a plan nothing says 100 Mbit/s is low


def test_a_partial_or_failed_speed_result_is_not_a_measurement_and_raises_nothing():
    for outcome, st in (("partial", "inconclusive"), ("inconclusive", "inconclusive"), ("error", "failed"), (None, "not_available")):
        _, ms, hs, _ = build(speed=(sp("download", "CORE", 400.0, outcome), sp("download", "INTERNET", 10.0, outcome)))
        assert hs == [] and {m["status"] for m in ms if m["group"] in ("CORE", "INTERNET")} == {st}
        assert all(m["value"] is None for m in ms if m["group"] in ("CORE", "INTERNET"))


def test_packet_loss_needs_a_real_sample_and_dns_needs_a_working_ping():
    assert codes(metrics=[ex("ip.loss_pct", "CORE", 20.0, "%", sample_size=2)]) == []
    assert codes(metrics=[ex("ip.loss_pct", "CORE", 20.0, "%", sample_size=5)]) == ["PACKET_LOSS"]
    assert codes(metrics=[ex("ip.loss_pct", "CORE", 0.0, "%", sample_size=5)]) == []
    assert codes(metrics=[ex("dns.lookup_ok", "INTERNET", False)]) == []
    assert codes(metrics=[ex("dns.lookup_ok", "INTERNET", False), ex("ip.rtt_avg_ms", "CORE", 12.0, "ms")]) == ["DNS_POTENTIAL"]
    assert codes(metrics=[ex("dns.lookup_ok", "INTERNET", True), ex("ip.rtt_avg_ms", "CORE", 12.0, "ms")]) == []


def test_every_hypothesis_carries_evidence_a_check_and_caveats_and_no_score_exists():
    _, _, hs, s = build(speed=(sp("download", "CORE", 400.0), sp("download", "INTERNET", 100.0)))
    for h in hs:
        assert h["evidence_metric_ids"] and h["recommended_check"] and h["caveats"] and h["confidence"] in ("low", "medium")
    assert not any(k in s for k in ("score", "quality", "grade", "percent"))
