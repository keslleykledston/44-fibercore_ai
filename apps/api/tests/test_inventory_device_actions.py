"""Actions on a CPE (runs after test_edge: the session-scoped `inv` fixture adds Edges to provider A) from its screen (phase Dispositivos, delivery 4). They add no way to write: a request is the existing job (preview + submit) and
stays behind the write gate, another person's approval, the signed envelope and the Edge. What is tested here is the screen's contract."""
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.api import jobs as jobs_mod
from tests.conftest import agent, hdr
from tests.test_jobs_bench import _approver, _bench, _cleanup, _cpe, _flag  # noqa: F401  (the autouse cleanup fixture comes along)

SSID = {"ssid": "BANCADA-H3"}


def _key():
    return {"Idempotency-Key": f"ui-{uuid4().hex}"}


def _post(client, h, cpe, op="reboot_cpe", params=None, key=None):
    return client.post(f"/v1/cpes/{cpe}/actions/{op}", headers={**h, **(key or _key())}, json={"params": params or {}})


def _actions(client, h, cpe):
    r = client.get(f"/v1/cpes/{cpe}/actions", headers=h)
    assert r.status_code == 200, r.text
    return {i["operation"]: i for i in r.json()["items"]}


def _jobs(migrated):
    with migrated.connect() as c:
        return c.execute(text("SELECT status FROM jobs WHERE operation IN ('reboot_cpe','set_wifi_ssid') ORDER BY created_at")).scalars().all()


def test_the_screen_offers_only_what_the_registry_has_observed_for_this_exact_profile(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    h = hdr(client, "alice", seed, "A")
    a = _actions(client, h, cpe)
    assert set(a) == {"reboot_cpe", "set_wifi_ssid"}
    assert all(not i["offered"] and i["reason"] == "capability_not_observed" and i["homologated"] is False for i in a.values())
    _bench(migrated, seed, inv, cpe)  # observed entry for reboot_cpe on this profile, bench target, authorization
    a = _actions(client, h, cpe)
    assert (a["reboot_cpe"]["offered"], a["reboot_cpe"]["reason"], a["reboot_cpe"]["bench_target"]) == (True, None, True)
    assert a["set_wifi_ssid"]["offered"] is False and a["set_wifi_ssid"]["needs_params"] is True


def test_identified_or_unsupported_entries_are_not_observed(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, cert="identified")
    assert _actions(client, hdr(client, "alice", seed, "A"), cpe)["reboot_cpe"]["offered"] is False


def test_who_may_ask_follows_the_catalog(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe)
    with migrated.begin() as c:
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, verified_at, evidence_ref) "
                       "SELECT tenant_id, vendor, model, firmware, protocol, 'set_wifi_ssid', status, certification, verified_at, evidence_ref FROM device_capabilities "
                       "WHERE operation = 'reboot_cpe'"))
    # dave is noc_n1 (reads the inventory, cannot ask); carol is an auditor of A (no inventory:read)
    dave = _actions(client, hdr(client, "dave", seed, "A"), cpe)
    assert all(not i["offered"] and i["reason"] == "not_permitted" for i in dave.values())
    assert client.get(f"/v1/cpes/{cpe}/actions", headers=hdr(client, "carol", seed, "A")).status_code == 403
    assert _post(client, hdr(client, "dave", seed, "A"), cpe).status_code == 403
    assert _post(client, hdr(client, "carol", seed, "A"), cpe).status_code == 403
    assert _jobs(migrated) == []


def test_a_request_without_an_observed_entry_creates_no_job(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    r = _post(client, hdr(client, "alice", seed, "A"), cpe)
    assert (r.status_code, r.json()["detail"]) == (409, "capability_not_observed")
    assert _jobs(migrated) == []


def test_every_write_stays_behind_the_global_gate_when_the_bench_path_is_closed(client, seed, inv, migrated):
    assert jobs_mod.HOMOLOGATED_WRITES == frozenset()
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe)  # observed and authorized, but the tenant flag `bench_writes` is OFF
    h = hdr(client, "alice", seed, "A")
    r = _post(client, h, cpe)
    assert r.status_code == 200
    j = r.json()
    assert (j["outcome"], j["reason"], j["job"]["status"]) == ("blocked", "operation_not_homologated", "CANCELLED")
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204   # nothing reaches an Edge
    with migrated.connect() as c:
        assert c.execute(text("SELECT state FROM bench_authorizations")).scalar() == "open"      # and the owner's authorization is untouched
        act = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE action = 'device.action_blocked' ORDER BY created_at DESC LIMIT 1")).scalar()
    assert act["reason"] == "operation_not_homologated" and act["operation"] == "reboot_cpe"


def test_a_bench_target_with_the_owners_authorization_becomes_a_pending_job_and_still_needs_another_person(client, seed, inv, migrated):
    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    key = _key()
    r = _post(client, h, cpe, key=key)
    j = r.json()
    assert (r.status_code, j["outcome"], j["reason"], j["job"]["status"]) == (200, "submitted", None, "PENDING_APPROVAL")
    assert j["job"]["required_approvals"] == 1
    # the same request again (double click, retry) is the same job
    again = _post(client, h, cpe, key=key).json()
    assert (again["outcome"], again["job"]["id"]) == ("existing", j["job"]["id"])
    assert _jobs(migrated) == ["PENDING_APPROVAL"]
    with migrated.connect() as c:
        assert c.execute(text("SELECT state FROM bench_authorizations")).scalar() == "open"        # asking does not spend the authorization
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'device.action_requested'")).scalar_one() >= 1
    done = client.post(f"/v1/jobs/{j['job']['id']}/approve", headers=_approver(client, seed, migrated))
    assert done.json()["status"] == "APPROVED"


def test_a_target_that_is_not_a_bench_target_is_refused_by_the_engine_not_by_this_layer(client, seed, inv, migrated):
    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, target=False)
    j = _post(client, hdr(client, "alice", seed, "A"), cpe).json()
    assert (j["outcome"], j["reason"], j["job"]["status"]) == ("blocked", "target_not_bench", "CANCELLED")


def test_wifi_name_is_the_catalogs_and_nothing_else(client, seed, inv, migrated):
    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, op="set_wifi_ssid", params=SSID)
    h = hdr(client, "alice", seed, "A")
    for bad in ({}, {"ssid": "MeuWifi"}, {"ssid": "BANCADA-h3"}, {"ssid": "BANCADA-H3", "extra": "x"}, {"ssid": "BANCADA-" + "A" * 17}):
        assert _post(client, h, cpe, "set_wifi_ssid", bad).status_code == 422, bad
    assert _jobs(migrated) == []
    j = _post(client, h, cpe, "set_wifi_ssid", SSID).json()
    assert (j["outcome"], j["job"]["status"]) == ("submitted", "PENDING_APPROVAL")


def test_reboot_takes_no_parameters(client, seed, inv, migrated):
    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe)
    assert _post(client, hdr(client, "alice", seed, "A"), cpe, params={"force": True}).status_code == 422


def test_another_providers_cpe_does_not_exist(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    hb = hdr(client, "bob", seed, "B")
    assert client.get(f"/v1/cpes/{cpe}/actions", headers=hb).status_code == 404
    assert _post(client, hb, cpe).status_code == 404
    assert _post(client, hdr(client, "alice", seed, "A"), str(uuid4())).status_code == 404


def test_the_idempotency_key_is_required_and_cannot_change_the_intent(client, seed, inv, migrated):
    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    assert client.post(f"/v1/cpes/{cpe}/actions/reboot_cpe", headers=h, json={"params": {}}).status_code == 422
    k = _key()
    assert _post(client, h, cpe, key=k).status_code == 200
    with migrated.begin() as c:
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, verified_at, evidence_ref) "
                       "SELECT tenant_id, vendor, model, firmware, protocol, 'set_wifi_ssid', status, certification, verified_at, evidence_ref FROM device_capabilities "
                       "WHERE operation = 'reboot_cpe'"))
    assert _post(client, h, cpe, "set_wifi_ssid", SSID, key=k).status_code == 409   # same key, other operation


def test_repeating_a_blocked_request_still_says_blocked_with_the_reason(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe)   # flag off: the first answer is blocked
    h = hdr(client, "alice", seed, "A")
    key = _key()
    first = _post(client, h, cpe, key=key).json()
    again = _post(client, h, cpe, key=key).json()          # the answer was lost; the screen asks again with the same key
    assert (first["outcome"], first["reason"]) == ("blocked", "operation_not_homologated")
    assert (again["outcome"], again["reason"], again["job"]["id"], again["job"]["status"]) == ("blocked", "operation_not_homologated", first["job"]["id"], "CANCELLED")
    with migrated.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE target_id = :c"), {"c": cpe}).scalar_one() == 1   # still ONE job for this CPE
