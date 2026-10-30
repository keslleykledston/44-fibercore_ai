"""Diagnostic jobs (SD-001 / ADR-0028): passive, read-only, customer-centred; evidence and findings conform to the SD-001 contract, every
finding cites existing evidence, old/absent data is never a verdict, results replay, tenant-isolated and append-only."""
import ast
import json
import random
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import diagnostic_jobs
from tests.conftest import _now, agent, hdr, snap
from tests.test_sd001_contracts import CANON, OVERLAY, _v

PFX = "DJB-"


def _component(name):  # the implemented operations live in the CANONICAL contract
    return {"$ref": f"#/components/schemas/{name}", "components": CANON["components"]}


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features"))
        c.execute(text("DELETE FROM diagnostic_jobs"))
        c.execute(text("DELETE FROM onu_cpe_links WHERE cpe_id IN (SELECT id FROM cpes WHERE canonical_serial LIKE 'DJB-%')"))
        c.execute(text("DELETE FROM associations WHERE customer_id IN (SELECT id FROM customers WHERE erp_source = 'djbtest')"))
        c.execute(text("DELETE FROM customers WHERE erp_source = 'djbtest'"))
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'DJB-%'"))
        c.execute(text("DELETE FROM incident_onus WHERE onu_id IN (SELECT id FROM onus WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-DJB-%'))"))
        c.execute(text("DELETE FROM incidents WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-DJB-%')"))
        c.execute(text("DELETE FROM onus WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-DJB-%')"))
        c.execute(text("DELETE FROM pon_ports WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-DJB-%')"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-DJB-%'"))


def _flags(migrated, tenant, *names):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        for n in names:
            c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,true)"), {"t": tenant, "f": n})


def _on(migrated, seed):
    _flags(migrated, seed["A"], "smart_diagnostics_jobs", "diagnostic_engine")


def _onu(client, inv, name, serial, status="online", observed=None):
    r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(
        inv, "a1", name=name, observed=observed, pons=[{"pon_path": "0/5/0", "status": "up", "complete": True}],
        onus=[{"serial": serial, "pon_path": "0/5/0", "status": status, "rx_dbm": -21.5}]))
    assert r.status_code == 202, r.text


def _cpe(client, inv, serial, metrics=None):
    ext = f"ext-{serial.lower()}"
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "cpes": [
        {"canonical_serial": serial, "vendor": "V", "model": "M", "binding": {"protocol": "tr069", "external_id": ext, "connector_id": "c-djb"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    if metrics:
        st = {"edge_id": str(inv["a1"]["edge"]), "observed_at": _now(), "states": [
            {"binding": {"protocol": "tr069", "external_id": ext, "connector_id": "c-djb"}, "metrics": metrics}]}
        assert client.post("/v1/edge/cpe-state", headers=agent(client, inv, "a1"), json=st).status_code == 202


def _m(name, scope, value, at=None):
    return {"name": name, "scope": scope, "value": value, "captured_at": at or _now(-60)}


def _world(client, inv, seed, migrated, serial="DJB-0001", onu_status="online", metrics=None, link=True, observed=None, with_cpe=True):
    """customer (approved ONU) [+ confirmed link to a CPE with state]; returns (customer_id, onu_id, cpe_id)."""
    h = hdr(client, "alice", seed, "A")
    _onu(client, inv, f"OLT-DJB-N{serial[-4:]}", serial, onu_status, observed)
    onu = client.get(f"/v1/onus?serial={serial}", headers=h).json()[0]["id"]
    cpe = None
    if with_cpe:
        _cpe(client, inv, serial, metrics)
        cpe = next(c["id"] for c in client.get("/v1/cpes", headers=h).json() if c["canonical_serial"] == serial)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        cust = c.execute(text("INSERT INTO customers(tenant_id, erp_source, erp_customer_id, display_name, document_last4, contract_status, "
                              "source_updated_at) VALUES (:t,'djbtest',:e,'Cliente Nome Completo','4321','active',now()) RETURNING id"),
                         {"t": seed["A"], "e": f"E-{serial}"}).scalar()
        c.execute(text("INSERT INTO associations(tenant_id, onu_id, customer_id, status, score, evidence, reviewed_by, reviewed_at) "
                       "VALUES (:t,:o,:c,'approved',100,CAST('{}' AS jsonb),:r,now())"), {"t": seed["A"], "o": onu, "c": cust, "r": seed["alice"]})
        if cpe and link:
            c.execute(text("INSERT INTO onu_cpe_links (tenant_id, onu_id, cpe_id, status, confidence, evidence, reviewed_by, reviewed_at) "
                           "VALUES (:t,:o,:c,'confirmed',1,CAST('{\"rule\":\"manual\"}' AS jsonb),:r,now())"),
                      {"t": seed["A"], "o": onu, "c": cpe, "r": seed["alice"]})
    return str(cust), onu, cpe


def _post(client, h, body, key=None):
    return client.post("/v1/diagnostics/jobs", headers={**h, "Idempotency-Key": key or uuid.uuid4().hex}, json=body)


DISCONNECTED = [_m("wan_link_status", "link/1", "Up"), _m("wan_connection_status", "ppp/3/1", "Disconnected"), _m("uptime_seconds", "ppp/3/1", 120)]


def test_everything_is_off_by_default(client, seed):
    h = hdr(client, "alice", seed, "A")
    r = _post(client, h, {"customer_id": str(uuid.uuid4()), "mode": "passive"})
    assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
    assert client.get(f"/v1/diagnostics/jobs/{uuid.uuid4()}", headers=h).status_code == 403


def test_job_gathers_evidence_cites_it_conforms_to_the_contract_and_replays(client, seed, inv, migrated):
    _on(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    cust, onu, cpe = _world(client, inv, seed, migrated, metrics=DISCONNECTED)
    with migrated.begin() as c:
        before = c.execute(text("SELECT (SELECT count(*) FROM incidents), (SELECT count(*) FROM cpe_state), (SELECT count(*) FROM events_outbox), "
                                "(SELECT count(*) FROM diagnostic_runs)")).one()
    r = _post(client, h, {"customer_id": cust, "mode": "passive", "ticket_id": "TCK-1001"})
    assert r.status_code == 202, r.text
    rec = r.json()
    assert not _v(_component("DiagnosticJobReceipt"), rec), rec
    assert set(rec) == {"job_id", "status", "created_at"} and rec["status"] in ("complete", "partial")
    job = client.get(f"/v1/diagnostics/jobs/{rec['job_id']}", headers=h).json()
    assert not _v(_component("DiagnosticJob"), {k: v for k, v in job.items() if k not in ("reproducible", "rule_runs")}), job
    assert job["run_id"] is None and job["reproducible"] is True and {x["rule_id"] for x in job["rule_runs"]} == {"R-D001", "R-D002"}
    ids = {e["evidence_id"] for e in job["evidences"]}
    assert ids >= {"ev-onu1-status", "ev-onu1-rx", "ev-cpe1-wan_link_status-link-1", "ev-cpe1-wan_connection_status-ppp-3-1"}
    assert all(set(f["evidence_ids"]) <= ids for f in job["findings"])
    wan = next(f for f in job["findings"] if f["category"] == "WAN_LINK")
    assert wan["certainty"] == "possible" and "hipótese" in wan["explanation"]
    # the finding cites exactly what R-D002 read (link + connection); uptime is shown as evidence but does not back the hypothesis
    assert wan["evidence_ids"] == ["ev-cpe1-wan_connection_status-ppp-3-1", "ev-cpe1-wan_link_status-link-1"]
    assert "ev-cpe1-uptime_seconds-ppp-3-1" in ids
    assert not [f for f in job["findings"] if f["certainty"] == "confirmed"]  # an online ONU and a rule hypothesis: nothing is confirmed
    by = {e["evidence_id"]: e for e in job["evidences"]}
    assert by["ev-onu1-status"]["value"] == "online" and by["ev-onu1-rx"]["value"] == -21.5 and by["ev-onu1-rx"]["unit"] == "dBm"
    assert by["ev-cpe1-wan_connection_status-ppp-3-1"]["value"] == "Disconnected" and by["ev-cpe1-wan_connection_status-ppp-3-1"]["method"] == "genieacs_nbi"
    # read-only: no incident, no state, no event, no diagnostic_run; nothing about the customer or the serial is stored
    with migrated.begin() as c:
        after = c.execute(text("SELECT (SELECT count(*) FROM incidents), (SELECT count(*) FROM cpe_state), (SELECT count(*) FROM events_outbox), "
                               "(SELECT count(*) FROM diagnostic_runs)")).one()
        row = c.execute(text("SELECT request, evidences, findings, rule_runs FROM diagnostic_jobs")).one()
        audited = c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'diagnostics.job.create'")).scalar()
    assert after == before and audited == 1
    blob = json.dumps([row.request, row.evidences, row.findings, row.rule_runs])
    assert "DJB-0001" not in blob and "Cliente Nome" not in blob and "4321" not in blob


def test_pon_finding_cites_the_aggregate_the_rule_judged(client, seed, inv, migrated):
    _on(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    ok = [{"serial": f"DJB-P{i:02d}", "pon_path": "0/5/0", "status": "online", "rx_dbm": -20.0} for i in range(10)]
    bad = [ok[0]] + [{**o, "status": "los", "rx_dbm": None} for o in ok[1:]]
    for items, at in ((ok, _now(-600)), (bad, _now(-540))):
        r = client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(
            inv, "a1", name="OLT-DJB-PON", observed=at, pons=[{"pon_path": "0/5/0", "status": "up", "complete": True}], onus=items))
        assert r.status_code == 202, r.text
    onu = client.get("/v1/onus?serial=DJB-P01", headers=h).json()[0]["id"]
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        cust = c.execute(text("INSERT INTO customers(tenant_id, erp_source, erp_customer_id, display_name, document_last4, contract_status, "
                              "source_updated_at) VALUES (:t,'djbtest','E-PON','Cliente','1111','active',now()) RETURNING id"), {"t": seed["A"]}).scalar()
        c.execute(text("INSERT INTO associations(tenant_id, onu_id, customer_id, status, score, evidence, reviewed_by, reviewed_at) "
                       "VALUES (:t,:o,:c,'approved',100,CAST('{}' AS jsonb),:r,now())"), {"t": seed["A"], "o": onu, "c": cust, "r": seed["alice"]})
    job = client.get(f"/v1/diagnostics/jobs/{_post(client, h, {'customer_id': str(cust), 'mode': 'passive', 'requested_domains': ['pon']}).json()['job_id']}",
                     headers=h).json()
    assert not _v(_component("DiagnosticJob"), {k: v for k, v in job.items() if k not in ("reproducible", "rule_runs")}), job
    f = next(x for x in job["findings"] if x["category"] == "PON_MASS_OUTAGE")
    by = {e["evidence_id"]: e for e in job["evidences"]}
    assert f["certainty"] == "likely" and f["evidence_ids"] == ["ev-onu1-status", "ev-pon1-drops", "ev-pon1-online"]
    assert by["ev-pon1-online"]["value"] == 1 and by["ev-pon1-drops"]["value"] == 9 and by["ev-pon1-drops"]["unit"] == "count"
    assert by["ev-pon1-drops"]["metric"] == "pon_onus_recent_drops" and by["ev-pon1-online"]["status"] == "available"
    # the ENVELOPE says which PON and which window: the PON counts carry scope_ref + window_seconds, the ONU evidence carries its own
    # scope_ref and the PON as parent_ref; the references are opaque (no serial, no path) and the explanation repeats them
    pon_ref = by["ev-pon1-drops"]["scope_ref"]
    assert re.fullmatch(r"pon-[0-9a-f]{16}", pon_ref) and by["ev-pon1-online"]["scope_ref"] == pon_ref == by["ev-onu1-status"]["parent_ref"]
    assert by["ev-pon1-drops"]["window_seconds"] == by["ev-pon1-online"]["window_seconds"] == 21600
    assert re.fullmatch(r"onu-[0-9a-f]{16}", by["ev-onu1-status"]["scope_ref"]) and "DJB-P01" not in json.dumps(job) and "0/5/0" not in json.dumps(job)
    assert f["explanation"] == (f"Na PON {pon_ref} (a da ONU do cliente), 9 ONUs caíram nos últimos 6 h e 1 seguem online (regra R-D001 v1); "
                                "hipótese de queda coletiva, a confirmar com o incidente e eventos de campo.")
    assert any(x["category"] == "ONU_OFFLINE" and x["certainty"] == "confirmed" for x in job["findings"])
    assert job["reproducible"] is True and [x["rule_id"] for x in job["rule_runs"]] == ["R-D001"]


def test_idempotency_same_key_same_job_different_request_conflicts(client, seed, inv, migrated):
    _on(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    cust, _, _ = _world(client, inv, seed, migrated, metrics=DISCONNECTED)
    body = {"customer_id": cust, "mode": "passive"}
    a, b = _post(client, h, body, key="idem-key-0001"), _post(client, h, {**body, "requested_domains": ["wan", "pon"]}, key="idem-key-0001")
    assert a.status_code == b.status_code == 202 and a.json()["job_id"] == b.json()["job_id"]  # same request, domains are a set
    assert _post(client, h, {**body, "requested_domains": ["pon"]}, key="idem-key-0001").status_code == 409
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM diagnostic_jobs")).scalar() == 1


def test_an_onu_the_olt_reports_down_is_confirmed_as_a_fact_and_nothing_more(client, seed, inv, migrated):
    _on(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    cust, _, _ = _world(client, inv, seed, migrated, serial="DJB-0002", onu_status="los", with_cpe=False)
    job = client.get(f"/v1/diagnostics/jobs/{_post(client, h, {'customer_id': cust, 'mode': 'passive'}).json()['job_id']}", headers=h).json()
    down = next(f for f in job["findings"] if f["category"] == "ONU_OFFLINE")
    assert down["certainty"] == "confirmed" and "não indica a causa" in down["explanation"] and down["evidence_ids"] == ["ev-onu1-status"]
    assert any(f["category"] == "INCONCLUSIVE" and "vínculo confirmado" in f["explanation"] for f in job["findings"])  # no CPE: WAN not evaluated
    assert job["status"] == "partial" and job["data_quality"] == "partial"


def test_old_or_absent_data_is_insufficient_evidence_never_a_verdict(client, seed, inv, migrated):
    _on(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    old = _world(client, inv, seed, migrated, serial="DJB-0003", metrics=[_m("wan_connection_status", "ppp/1/1", "Disconnected", _now(-7200))],
                 observed=_now(-3600))
    job = client.get(f"/v1/diagnostics/jobs/{_post(client, h, {'customer_id': old[0], 'mode': 'passive'}).json()['job_id']}", headers=h).json()
    cats = {f["category"]: f for f in job["findings"]}
    assert cats["INCONCLUSIVE"]["certainty"] == "insufficient_evidence" and cats["CPE_STALE_DATA"]["certainty"] == "insufficient_evidence"
    assert "WAN_LINK" not in cats and "ONU_OFFLINE" not in cats and "PON_MASS_OUTAGE" not in cats
    assert job["data_quality"] == "stale" and job["status"] == "inconclusive"
    assert {e["status"] for e in job["evidences"]} == {"stale"}
    none = _world(client, inv, seed, migrated, serial="DJB-0004", with_cpe=False)  # a customer without any approved ONU
    with migrated.begin() as c:
        c.execute(text("DELETE FROM associations WHERE customer_id = :c"), {"c": none[0]})
    empty = client.get(f"/v1/diagnostics/jobs/{_post(client, h, {'customer_id': none[0], 'mode': 'passive'}).json()['job_id']}", headers=h).json()
    assert empty["evidences"] == [] and empty["data_quality"] == "unsupported" and empty["status"] == "inconclusive"
    assert [f["category"] for f in empty["findings"]] == ["INCONCLUSIVE"]


def test_request_is_strict_and_scopes_are_validated(client, seed, inv, migrated):
    _on(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    cust, _, cpe = _world(client, inv, seed, migrated, metrics=DISCONNECTED)
    base = {"customer_id": cust, "mode": "passive"}
    for bad in ({**base, "mode": "guided"}, {**base, "requested_domains": ["wifi"]}, {**base, "service_id": str(uuid.uuid4())},
                {**base, "ticket_id": "AA:BB:CC:DD:EE:FF"}, {**base, "ticket_id": "x" * 65}, {**base, "extra": 1}, {"mode": "passive"},
                {**base, "customer_id": "not-a-uuid"}, {**base, "requested_domains": ["pon"] * 3}):
        assert _post(client, h, bad).status_code == 422, bad
    assert client.post("/v1/diagnostics/jobs", headers={**h, "Idempotency-Key": "short"}, json=base).status_code == 422
    assert client.post("/v1/diagnostics/jobs", headers={**h, "Idempotency-Key": "AA:BB:CC:DD:EE:FF-too"}, json=base).status_code == 422
    assert client.post("/v1/diagnostics/jobs", headers=h, json=base).status_code == 422  # the key is required
    assert _post(client, h, {**base, "customer_id": str(uuid.uuid4())}).status_code == 404
    assert _post(client, h, {**base, "cpe_id": str(uuid.uuid4())}).status_code == 422  # not linked to this customer
    assert _post(client, h, {**base, "cpe_id": cpe}).status_code == 202


def test_jobs_are_tenant_isolated_and_append_only(client, seed, inv, migrated):
    _on(migrated, seed)
    _flags(migrated, seed["B"], "smart_diagnostics_jobs", "diagnostic_engine")
    h = hdr(client, "alice", seed, "A")
    cust, _, _ = _world(client, inv, seed, migrated, metrics=DISCONNECTED)
    jid = _post(client, h, {"customer_id": cust, "mode": "passive"}).json()["job_id"]
    hb = hdr(client, "bob", seed, "B")
    assert client.get(f"/v1/diagnostics/jobs/{jid}", headers=hb).status_code == 404
    assert _post(client, hb, {"customer_id": cust, "mode": "passive"}).status_code == 404  # another tenant's customer does not exist for B
    with migrated.begin() as c:
        c.execute(text("SET LOCAL ROLE fibercore_app"))
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
        assert c.execute(text("SELECT count(*) FROM diagnostic_jobs")).scalar() == 0
    for stmt in ("UPDATE diagnostic_jobs SET status = 'failed'", "DELETE FROM diagnostic_jobs"):
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text("SET LOCAL ROLE fibercore_app"))
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(stmt))


# ---- the pure assembly ----------------------------------------------------------------------------------------------------------------
OPAQUE = re.compile(r"^(?![0-9A-Fa-f]{2}([-:.]?[0-9A-Fa-f]{2}){5}$)[A-Za-z0-9_-]{1,64}$")


def test_assemble_properties_over_random_subjects():
    rnd = random.Random(11)  # noqa: S311
    metrics = [("wan_link_status", "link/1", "Up"), ("wan_connection_status", "ppp/3/1", "Disconnected"), ("uptime_seconds", "ppp/3/1", 5),
               ("wifi_channel", "radio/1", 6)]
    for _ in range(600):
        subjects = []
        for n in range(1, rnd.randint(0, 3) + 1):
            cpe = None
            if rnd.random() < 0.7:
                states = [{"metric": m, "scope": s, "value": v, "captured_at": "2026-10-29T10:00:00Z", "received_at": "2026-10-29T10:00:01Z",
                           "fresh": rnd.random() < 0.6} for m, s, v in rnd.sample(metrics, rnd.randint(0, 4))]
                status = rnd.choice(["unknown", "observed", "inferred"])
                cpe = {"states": states, "finding": {"status": status, "suspected_cause": rnd.choice(
                    ["wan_link_down", "wan_session_down", "wan_connection_down"]) if status == "inferred" else None}}
            subjects.append({"n": n, "onu": {"ref": f"onu-{n:016d}", "status": rnd.choice(["online", "offline", "los", "dying_gasp", "weird"]), "rx_dbm": rnd.choice([None, -20.1]),
                                             "observed_at": "2026-10-29T10:00:00Z", "fresh": rnd.random() < 0.6},
                             "pon_finding": rnd.choice([None, {"status": "inferred", "rule_id": "R-D001", "rule_version": 1}, {"status": "unknown"},
                                                        {"status": "observed"}]),
                             "pon": rnd.choice([None, {"ref": "pon-0000000000000001", "online": 1, "recent_drops": 9, "window_seconds": 300, "reference_at": "2026-10-29T10:00:00Z",
                                                          "fresh": rnd.random() < 0.5},
                                                {"ref": "pon-0000000000000001", "online": 0, "recent_drops": 0, "window_seconds": 300, "reference_at": None,
                                                 "fresh": False}]),
                             "cpe": cpe})
        domains = rnd.choice([["pon", "wan"], ["pon"], ["wan"]])
        cut = rnd.random() < 0.1
        out = diagnostic_jobs.assemble(subjects, domains, truncated=cut)
        assert json.loads(json.dumps(out)) == out and out == diagnostic_jobs.assemble(subjects, domains, truncated=cut)  # JSON-native, deterministic
        ids = [e["evidence_id"] for e in out["evidences"]]
        assert len(ids) == len(set(ids)) and all(OPAQUE.fullmatch(i) for i in ids)
        for f in out["findings"]:
            assert set(f["evidence_ids"]) <= set(ids)
            if f["certainty"] in ("confirmed", "likely", "possible"):
                assert f["evidence_ids"], f                    # a claim always cites evidence
            if f["certainty"] == "confirmed":
                assert f["category"] == "ONU_OFFLINE"          # only a plain OLT fact is confirmed; rule hypotheses never are
            by_id = {e["evidence_id"]: e for e in out["evidences"]}
            if f["category"] == "WAN_LINK":                    # only what R-D002 read backs it: never uptime, never Wi-Fi
                assert {by_id[i]["metric"] for i in f["evidence_ids"]} <= {"wan_link_status", "wan_connection_status"}, f
            if f["category"] == "PON_MASS_OUTAGE":             # the aggregate the rule judged is cited, with its counts
                assert {by_id[i]["metric"] for i in f["evidence_ids"]} >= {"onu_status", "pon_onus_online", "pon_onus_recent_drops"}, f
        assert all(e["status"] != "available" or e["value"] is not None for e in out["evidences"])  # a value is never invented
        if not out["evidences"]:
            assert out["data_quality"] == "unsupported" and out["status"] == "inconclusive"
        if out["status"] == "complete":
            assert out["data_quality"] == "fresh" and all(e["status"] == "available" for e in out["evidences"])
            assert not [f for f in out["findings"] if f["certainty"] == "insufficient_evidence"]


def test_assembly_is_pure():
    src = Path(diagnostic_jobs.__file__).read_text(encoding="utf-8")
    imported = {n.module.split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
                for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert imported <= {"__future__"}, imported


def test_canonical_contract_has_the_operations_and_shares_schemas_with_the_overlay_without_drift():
    ops = CANON["paths"]
    assert ops["/diagnostics/jobs"]["post"]["operationId"] == "createDiagnosticJob" and "get" in ops["/diagnostics/jobs/{job_id}"]
    shared = ["CreateDiagnosticJob", "DiagnosticJobReceipt", "DiagnosticJob", "Evidence", "Finding", "FindingCategory", "MetricName",
              "StateValue", "OpaqueRef", "SafeText"]
    for name in shared:  # the overlay keeps its copies for the operations not implemented yet: they must not drift
        assert CANON["components"]["schemas"][name] == OVERLAY["components"]["schemas"][name], name
    assert "/diagnostics/jobs" not in OVERLAY["paths"] and "/diagnostics/jobs/{job_id}" not in OVERLAY["paths"]  # moved, not duplicated


def test_the_api_accepts_nothing_the_contract_does_not_define():
    props = CANON["components"]["schemas"]["CreateDiagnosticJob"]["properties"]
    from app.api.diagnostic_jobs import CreateDiagnosticJob

    assert set(CreateDiagnosticJob.model_fields) <= set(props)  # a subset on purpose (ADR-0028): passive only, domains pon/wan
    assert set(CANON["components"]["schemas"]["CreateDiagnosticJob"]["required"]) >= {"customer_id", "mode"}
