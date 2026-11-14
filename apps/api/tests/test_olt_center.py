"""Centro de OLT, metade nuvem (ADR-0046 D3/D4/D5/D6, migration 0051).

What is proved here: the rules between the connection fields (pure); the database (constraints, nobody but `app_olt_edge_report` writes the trust state, the trigger demotes it); registration/patch through the API
(defaults by protocol, validation, the address only masked, no secret or full address in any response/log/audit); the kind `olt_connection` through the existing delivery channel with ITS OWN permission and flag
(`fleet:provision` + `fleet_provision`), independent of the credential kinds; Telnet refused for every kind and every path (and a switch to Telnet cancelling what waited); the Edge's result with `awaiting_local_trust`;
`POST /v1/edge/managed-olts/state` touching only the caller Edge's own OLTs (the rest is `ignored`, never an error that reveals existence); RLS between two tenants for the new fields; the Edge simulated by the tests."""
from __future__ import annotations

import base64
import hashlib
import inspect
import json
import logging
import time
import uuid

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api import deps
from app.core import fleet, olt_secrets
from app.core.rbac_matrix import _routes
from tests import olt_secret_helpers as H
from tests.conftest import JOB_SEED_B64, agent, hdr
from tests.test_olt_secrets import Ctx, _sqla

ADDR = "10.77.88.99"                  # the full address: must never come back from any read, nor appear in a log or in the audit trail
HK = "SHA256:" + base64.b64encode(hashlib.sha256(b"fibercore-test-host").digest()).decode().rstrip("=")
HK2 = "SHA256:" + base64.b64encode(hashlib.sha256(b"another-host").digest()).decode().rstrip("=")
FLAGS = ("fleet_manager", "fleet_secrets", "fleet_provision")


def _flags(migrated, tenant, **flags):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        for name, on in flags.items():
            c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,:v) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = :v"), {"t": tenant, "f": name, "v": on})


@pytest.fixture(autouse=True)
def _clean(migrated):
    def wipe():
        with migrated.begin() as c:
            c.execute(text("DELETE FROM olt_secret_deliveries"))
            c.execute(text("DELETE FROM tenant_features WHERE feature IN ('fleet_manager', 'fleet_secrets', 'fleet_provision')"))
            c.execute(text("DELETE FROM olts WHERE name LIKE 'SEC-%' OR name LIKE 'CTR-%'"))
            c.execute(text("UPDATE edges SET seal_public_key = NULL, seal_key_id = NULL, seal_key_state = NULL, seal_key_reported_at = NULL, seal_key_confirmed_by = NULL, seal_key_confirmed_at = NULL"))
    wipe()
    yield
    wipe()


@pytest.fixture
def ctx(client, seed, inv, migrated):
    c = Ctx(client, seed, inv, migrated)
    _flags(migrated, seed["A"], fleet_manager=True, fleet_secrets=True, fleet_provision=True)
    return c


def reach(migrated, olt, **kw):
    """Arrangement (owner): how the OLT is reached. Goes through the same trigger a user route would."""
    fields = {"mgmt_address": ADDR, "mgmt_protocol": "ssh", "mgmt_port": 22, "mgmt_transport": "cli", "ssh_mode": "exec", "host_key_sha256": HK, **kw}
    sets = ", ".join(f"{k} = {'CAST(:' + k + ' AS inet)' if k == 'mgmt_address' else ':' + k}" for k in fields)
    with migrated.begin() as c:
        c.execute(text(f"UPDATE olts SET {sets} WHERE id = :i"), {**fields, "i": olt})  # noqa: S608  (fixed column names, test arrangement)


def state(migrated, olt):
    with migrated.begin() as c:
        return c.execute(text("SELECT edge_trust_state, conn_applied_at, mgmt_protocol, mgmt_port, mgmt_transport, snmp_port, host_key_sha256, ssh_mode, legacy_ssh, host(mgmt_address) AS addr FROM olts WHERE id = :i"), {"i": olt}).one()


def make_conn(c, *, olt=None, olt_name=None, action="set", **over):
    did, exp = str(uuid.uuid4()), int(time.time()) + 1800
    aad = olt_secrets.aad(tenant_id=c.tenant, edge_id=c.edge, olt_name=olt_name or c.olt_name, kind="olt_connection", delivery_id=did, key_id_=c.key_id, expires_at_unix=exp)
    plain = ({"kind": "olt_connection", "action": "set", "address": ADDR, "port": 22, "protocol": "ssh", "vendor": "huawei", "transport": "cli", "snmp_port": 161, "host_key_sha256": HK,
              "legacy_ssh": False, "ssh_mode": "exec", "cloud_id": str(olt or c.olt)} if action == "set" else {"kind": "olt_connection", "action": "remove", "cloud_id": str(olt or c.olt)})
    plain.update(over)
    blob = H.seal(c.point, json.dumps(plain, separators=(",", ":")).encode(), aad, c.key_id)
    return {"delivery_id": did, "kind": "olt_connection", "key_id": c.key_id, "expires_at": exp, "sealed": olt_secrets.b64url_encode(blob)}, aad, plain


def apply_conn(c, code=None):
    """The whole way of one connection: the person posts, the Edge (simulated) takes it and reports `applied`."""
    body, _, _ = make_conn(c)
    r = c.post(body)
    assert r.status_code == 202, r.text
    n = c.next().json()
    assert n["kind"] == "olt_connection" and n["id"] == r.json()["id"]
    assert c.result(n["id"], n["lease_token"], code=code).status_code == 204
    return n


def view(c, olt=None):
    r = c.client.get(f"/v1/fleet/olts/{olt or c.olt}", headers=c.h)
    assert r.status_code == 200, r.text
    return r.json()


def report(c, items, headers=None):
    return c.client.post("/v1/edge/managed-olts/state", headers=headers or c.ah, json={"items": items})


# ------------------------------------------------------------------ pure rules
def test_the_rules_between_the_connection_fields_are_pure_and_default_by_protocol():
    ssh = fleet.merge_connection({}, {"mgmt_protocol": "ssh"}, None)
    assert (ssh["mgmt_port"], ssh["mgmt_transport"], ssh["ssh_mode"], ssh["legacy_ssh"]) == (22, "cli", "exec", False)
    tel = fleet.merge_connection({}, {"mgmt_protocol": "telnet"}, None)
    assert (tel["mgmt_port"], tel["host_key_sha256"], tel["ssh_mode"], tel["legacy_ssh"]) == (23, None, None, False)
    assert fleet.merge_connection({}, {"mgmt_protocol": "ssh", "mgmt_port": 2222}, None)["mgmt_port"] == 2222            # a port typed wins over the default
    assert fleet.merge_connection({}, {}, None) == {"mgmt_protocol": None, "mgmt_port": None, "mgmt_transport": None, "snmp_port": None, "host_key_sha256": None, "ssh_mode": None, "legacy_ssh": False}
    cur = {"mgmt_protocol": "ssh", "mgmt_port": 2222, "mgmt_transport": "cli", "host_key_sha256": HK, "ssh_mode": "shell", "legacy_ssh": True}
    to_tel = fleet.merge_connection(cur, {"mgmt_protocol": "telnet"}, None)                                              # ssh -> telnet: the port of the new protocol, the ssh leftovers dropped
    assert (to_tel["mgmt_port"], to_tel["host_key_sha256"], to_tel["ssh_mode"], to_tel["legacy_ssh"]) == (23, None, None, False)
    assert fleet.merge_connection(cur, {"mgmt_protocol": "telnet", "mgmt_port": 2323}, None)["mgmt_port"] == 2323
    cleared = fleet.merge_connection(cur, {"mgmt_protocol": None}, None)
    assert (cleared["mgmt_port"], cleared["host_key_sha256"], cleared["ssh_mode"], cleared["legacy_ssh"]) == (None, None, None, False)
    snmp = fleet.merge_connection({}, {"mgmt_protocol": "ssh", "mgmt_transport": "snmp"}, "v2c")
    assert (snmp["mgmt_transport"], snmp["snmp_port"]) == ("snmp", 161)
    for sent, v, code in (({"mgmt_port": 22}, None, "protocol_required"), ({"host_key_sha256": HK}, None, "protocol_required"), ({"legacy_ssh": True}, None, "protocol_required"),
                          ({"mgmt_protocol": "telnet", "host_key_sha256": HK}, None, "telnet_has_no_ssh_fields"), ({"mgmt_protocol": "telnet", "ssh_mode": "exec"}, None, "telnet_has_no_ssh_fields"),
                          ({"mgmt_protocol": "telnet", "legacy_ssh": True}, None, "telnet_has_no_ssh_fields"),
                          ({"mgmt_protocol": "ssh", "mgmt_transport": "snmp"}, None, "snmp_transport_needs_v2c"), ({"mgmt_protocol": "ssh", "mgmt_transport": "snmp"}, "v3", "snmp_transport_needs_v2c")):
        with pytest.raises(fleet.ConnectionRuleError) as exc:
            fleet.merge_connection({}, sent, v)
        assert exc.value.code == code, sent
    assert fleet.HOST_KEY_RE.match(HK) and not fleet.HOST_KEY_RE.match(HK + "A") and not fleet.HOST_KEY_RE.match(HK[:-1]) and not fleet.HOST_KEY_RE.match(HK.replace("SHA256:", "MD5:"))


def test_readiness_is_the_chain_registered_connection_trust_credential_tested():
    def r(**kw):
        base = {"protocol": "ssh", "transport": "cli", "conn_applied": False, "trust": "none", "ssh_cred": False, "snmp_cred": False, "tested": False}
        return fleet.readiness(**{**base, **kw})["stage"]
    assert fleet.readiness(protocol=None, transport=None, conn_applied=False, trust="none", ssh_cred=False, snmp_cred=False, tested=False)["managed"] is False
    assert [r(), r(conn_applied=True), r(conn_applied=True, trust="awaiting_local_trust"), r(conn_applied=True, trust="trusted"), r(conn_applied=True, trust="trusted", ssh_cred=True),
            r(conn_applied=True, trust="trusted", ssh_cred=True, tested=True)] == ["registered", "connection_applied", "awaiting_trust", "trusted", "credential_applied", "tested"]
    assert r(conn_applied=True, trust="awaiting_local_trust", ssh_cred=True, tested=True) == "awaiting_trust"         # a credential stored while waiting does not make it usable
    assert r(conn_applied=True, trust="trusted", transport="snmp", ssh_cred=True) == "trusted"                        # the credential that counts is the one of the transport
    assert r(conn_applied=True, trust="trusted", transport="snmp", snmp_cred=True) == "credential_applied"
    assert r(protocol="telnet", conn_applied=True, trust="trusted", ssh_cred=True, tested=True) == "telnet_inventory"
    assert set(fleet.STAGES) >= {"registered", "telnet_inventory", "connection_applied", "awaiting_trust", "trusted", "credential_applied", "tested"}


def test_every_code_the_edge_may_report_has_a_sentence_in_portuguese():
    for code in (*olt_secrets.RESULT_CODES, *olt_secrets.APPLIED_CODES, "lease_exhausted", "connection_changed", "protocol_changed"):
        assert olt_secrets.CODE_PT.get(code), code
    assert "awaiting_local_trust" not in olt_secrets.RESULT_CODES                  # it rides on `applied`, it is not a failure
    assert {"protocol_not_supported", "vendor_not_supported", "vendor_not_allowed", "address_not_allowed", "port_not_allowed", "too_many_olts", "legacy_not_allowed", "name_conflict",
            "managed_olts_disabled"} <= set(olt_secrets.RESULT_CODES)


# ------------------------------------------------------------------ the database
def test_the_database_constrains_the_fields_and_only_the_narrow_function_writes_the_trust(ctx, app_url):
    c = ctx
    reach(c.migrated, c.olt)
    eng = _sqla(app_url)

    def run(*sqls, tenant=None):
        with eng.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant or c.tenant)})
            out = []
            for s, a in sqls:
                res = conn.execute(text(s), a)
                out.append(res.all() if res.returns_rows else [])
            return out
    try:
        for sql in ("UPDATE olts SET edge_trust_state = 'trusted' WHERE id = :o", "UPDATE olts SET conn_applied_at = now() WHERE id = :o", "UPDATE olts SET edge_trust_state = 'none', conn_applied_at = NULL WHERE id = :o"):
            with pytest.raises(DBAPIError) as exc:
                run((sql, {"o": c.olt}))
            assert "permission denied" in str(exc.value), sql
        for sql in ("UPDATE olts SET mgmt_port = 0", "UPDATE olts SET mgmt_port = 65536", "UPDATE olts SET snmp_port = 70000", "UPDATE olts SET mgmt_protocol = 'http'", "UPDATE olts SET mgmt_transport = 'ftp'",
                    "UPDATE olts SET ssh_mode = 'x'", "UPDATE olts SET host_key_sha256 = 'SHA256:short'", "UPDATE olts SET host_key_sha256 = 'MD5:' || repeat('a', 43)",
                    "UPDATE olts SET mgmt_protocol = NULL", "UPDATE olts SET mgmt_protocol = 'telnet'",   # the port / ssh fields still there: Telnet cannot hold them
                    "UPDATE olts SET mgmt_transport = 'snmp'"):   # SNMP transport needs snmp_version v2c (not set)
            with pytest.raises(DBAPIError) as exc:
                run((sql + " WHERE id = :o", {"o": c.olt}))
            assert "violates check constraint" in str(exc.value), sql
        run(("UPDATE olts SET mgmt_protocol = 'telnet', mgmt_port = 23, host_key_sha256 = NULL, ssh_mode = NULL WHERE id = :o", {"o": c.olt}))   # a coherent Telnet row is fine
        with pytest.raises(DBAPIError) as exc:   # ... and cannot get an ssh-only field back
            run(("UPDATE olts SET host_key_sha256 = :h WHERE id = :o", {"o": c.olt, "h": HK}))
        assert "violates check constraint" in str(exc.value)
        reach(c.migrated, c.olt)   # back to ssh
        # the function: only the Edge's own OLT of the session tenant; the state advances only with the record applied
        f = "SELECT app_olt_edge_report(:o, :e, :s)"
        assert run((f, {"o": c.olt, "e": c.edge, "s": "trusted"}))[0][0][0] == "ignored"                       # not applied yet
        assert run((f, {"o": c.olt, "e": c.inv["a2"]["edge"], "s": "connection_applied"}))[0][0][0] == "ignored"   # another Edge's claim
        assert run((f, {"o": c.olt, "e": c.edge, "s": "connection_applied"}))[0][0][0] == "changed"
        assert run((f, {"o": c.olt, "e": c.edge, "s": "awaiting_local_trust"}))[0][0][0] == "changed"
        assert run((f, {"o": c.olt, "e": c.edge, "s": "awaiting_local_trust"}))[0][0][0] == "same"
        assert run((f, {"o": c.olt, "e": c.edge, "s": "trusted"}))[0][0][0] == "changed"
        assert state(c.migrated, c.olt).edge_trust_state == "trusted"
        assert run((f, {"o": c.olt, "e": c.edge, "s": "trusted"}), tenant=c.seed["B"])[0][0][0] == "ignored"   # another tenant's session: RLS hides the row
        with pytest.raises(DBAPIError):
            run((f, {"o": c.olt, "e": c.edge, "s": "bogus"}))
        # the trigger: any change of HOW it is reached demotes what the Edge confirmed, by whatever route
        run(("UPDATE olts SET label = 'x' WHERE id = :o", {"o": c.olt}), ("UPDATE olts SET mgmt_port = 22 WHERE id = :o", {"o": c.olt}))   # unrelated / unchanged: nothing is demoted
        assert state(c.migrated, c.olt).edge_trust_state == "trusted"
        for sql in ("UPDATE olts SET mgmt_port = 2222", "UPDATE olts SET host_key_sha256 = 'SHA256:' || repeat('B', 43)", "UPDATE olts SET mgmt_address = '10.77.88.100'", "UPDATE olts SET ssh_mode = 'shell'",
                    "UPDATE olts SET legacy_ssh = true", "UPDATE olts SET snmp_port = 1161", "UPDATE olts SET mgmt_transport = 'snmp', snmp_version = 'v2c'"):
            reach(c.migrated, c.olt)
            run((f, {"o": c.olt, "e": c.edge, "s": "connection_applied"}), (f, {"o": c.olt, "e": c.edge, "s": "trusted"}))
            assert state(c.migrated, c.olt).edge_trust_state == "trusted", sql
            run((sql + " WHERE id = :o", {"o": c.olt}))
            st = state(c.migrated, c.olt)
            assert (st.edge_trust_state, st.conn_applied_at) == ("none", None), sql
    finally:
        eng.dispose()


# ------------------------------------------------------------------ registration and edition through the API
def _reg(c, name="CTR-1", **kw):
    return c.client.post("/v1/fleet/olts", headers=c.h, json={"name": name, "edge_id": str(c.edge), "vendor": "huawei", **kw})


def test_registration_defaults_by_protocol_masks_the_address_and_validates_every_field(ctx, caplog):
    c = ctx
    caplog.set_level(logging.DEBUG)
    r = _reg(c, mgmt_address=ADDR, mgmt_protocol="ssh", host_key_sha256=HK)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["connection"] == {"protocol": "ssh", "port": 22, "transport": "cli", "snmp_port": None, "host_key_sha256": HK, "ssh_mode": "exec", "legacy_ssh": False,
                               "trust_state": "none", "applied": False, "applied_at": None}
    assert v["mgmt_address_masked"] == "10.77.•.•" and ADDR not in r.text
    assert v["readiness"] == {"managed": True, "stage": "registered", "steps": {"connection": False, "trust": "none", "credential": False, "tested": False}}
    t = _reg(c, "CTR-2", mgmt_protocol="telnet", mgmt_address="10.77.1.1").json()
    assert (t["connection"]["protocol"], t["connection"]["port"], t["connection"]["host_key_sha256"], t["connection"]["ssh_mode"]) == ("telnet", 23, None, None)
    assert t["readiness"]["stage"] == "telnet_inventory"
    old = _reg(c, "CTR-3").json()   # an older-style registration: nothing about how it is reached
    assert old["connection"]["protocol"] is None and old["connection"]["port"] is None and old["readiness"]["managed"] is False
    s = _reg(c, "CTR-4", mgmt_protocol="ssh", mgmt_port=2222, mgmt_transport="snmp", snmp_version="v2c", host_key_sha256=HK, ssh_mode="shell", legacy_ssh=True).json()
    assert (s["connection"]["port"], s["connection"]["transport"], s["connection"]["snmp_port"], s["connection"]["ssh_mode"], s["connection"]["legacy_ssh"]) == (2222, "snmp", 161, "shell", True)
    for i, (bad, why) in enumerate((({"mgmt_port": 0}, 422), ({"mgmt_port": 65536}, 422), ({"mgmt_port": "22"}, 422), ({"mgmt_port": True}, 422), ({"snmp_port": 0}, 422), ({"mgmt_protocol": "http"}, 422),
                                    ({"mgmt_transport": "ftp"}, 422), ({"ssh_mode": "x"}, 422), ({"host_key_sha256": "SHA256:short"}, 422), ({"host_key_sha256": HK + "A"}, 422), ({"host_key_sha256": "MD5:" + "a" * 43}, 422),
                                    ({"edge_trust_state": "trusted"}, 422), ({"conn_applied_at": "2026-01-01T00:00:00Z"}, 422), ({"legacy_ssh": "yes"}, 422))):
        r = _reg(c, f"CTR-B{i}", **{"mgmt_protocol": "ssh", **bad})
        assert r.status_code == why, (bad, r.text)
        for v in bad.values():
            if isinstance(v, str) and len(v) > 12:
                assert v not in r.text
    for kw, code in (({"mgmt_port": 22}, "protocol_required"), ({"host_key_sha256": HK}, "protocol_required"), ({"mgmt_protocol": "telnet", "host_key_sha256": HK}, "telnet_has_no_ssh_fields"),
                     ({"mgmt_protocol": "telnet", "legacy_ssh": True}, "telnet_has_no_ssh_fields"), ({"mgmt_protocol": "ssh", "mgmt_transport": "snmp"}, "snmp_transport_needs_v2c"),
                     ({"mgmt_protocol": "ssh", "mgmt_transport": "snmp", "snmp_version": "v3"}, "snmp_transport_needs_v2c")):
        r = _reg(c, "CTR-BAD", **kw)
        assert (r.status_code, r.json()["detail"]) == (422, code), kw
    assert c.client.get("/v1/fleet/olts", headers=c.h).text.count(ADDR) == 0
    with c.migrated.begin() as conn:
        audits = conn.execute(text("SELECT action, evidence_redacted FROM audit_log WHERE action = 'fleet.olt.registered' AND evidence_redacted->>'name' LIKE 'CTR-%'")).all()
    blob = json.dumps([[a, e] for a, e in audits]) + caplog.text
    assert audits and ADDR not in blob and HK not in blob and "10.77.1.1" not in blob and '"2222"' not in blob
    assert next(e for _, e in audits if e["name"] == "CTR-1") == {"name": "CTR-1", "vendor": "huawei", "pop": None, "has_credential_ref": False, "has_mgmt_address": True, "snmp_version": None,
                                                                   "mgmt_protocol": "ssh", "mgmt_transport": "cli", "has_host_key": True}


def test_editing_how_it_is_reached_demotes_the_trust_cancels_the_waiting_connection_and_telnet_cancels_everything(ctx):
    c = ctx
    c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_address": ADDR, "mgmt_protocol": "ssh", "host_key_sha256": HK, "label": "x"})
    assert view(c)["connection"]["port"] == 22
    apply_conn(c, code="awaiting_local_trust")
    v = view(c)
    assert (v["connection"]["applied"], v["connection"]["trust_state"], v["readiness"]["stage"]) == (True, "awaiting_local_trust", "awaiting_trust")
    assert report(c, [{"cloud_id": str(c.olt), "state": "trusted"}]).json() == {"updated": 1, "ignored": 0}
    assert view(c)["readiness"]["stage"] == "trusted"
    assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"label": "other", "mgmt_port": 22, "host_key_sha256": HK, "mgmt_address": ADDR}).status_code == 200
    assert view(c)["connection"]["trust_state"] == "trusted"                                                     # nothing about the way of reaching it changed: nothing demoted
    waiting, _, _ = make_conn(c)
    assert c.post(waiting).status_code == 202                                                                    # a connection sealed for the CURRENT way waits for the Edge...
    cred, _ = c.make("ssh_login")
    assert c.post(cred).status_code == 202                                                                       # ...next to a credential
    r = c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"host_key_sha256": HK2})
    assert r.status_code == 200 and r.json()["connection"]["trust_state"] == "none" and r.json()["connection"]["applied"] is False and r.json()["readiness"]["stage"] == "registered"
    rows = {d["id"]: d for d in c.client.get(f"/v1/fleet/olts/{c.olt}/secret-deliveries", headers=c.h).json()["items"]}
    assert (rows[waiting["delivery_id"]]["status"], rows[waiting["delivery_id"]]["code"]) == ("CANCELLED", "connection_changed")   # the connection for the OLD fingerprint never reaches the Edge
    assert rows[cred["delivery_id"]]["status"] == "PENDING"                                                      # a credential is not tied to the way of reaching it
    assert not c.row(waiting["delivery_id"]).has_blob
    n = c.next().json()                                                                                          # the credential goes to the Edge as before
    assert n["kind"] == "ssh_login" and c.result(n["id"], n["lease_token"]).status_code == 204
    for kw in ({"mgmt_address": "10.77.88.100"}, {"mgmt_port": 2200}, {"mgmt_transport": "snmp", "snmp_version": "v2c"}, {"ssh_mode": "shell"}, {"legacy_ssh": True}, {"snmp_port": 1161}):
        apply_conn(c)
        assert view(c)["connection"]["applied"] is True
        assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json=kw).status_code == 200, kw
        assert view(c)["connection"]["applied"] is False and view(c)["connection"]["trust_state"] == "none", kw
    # ssh -> telnet: every waiting delivery (ANY kind) is cancelled with the blob erased, what is ssh-only is dropped, the port becomes 23, and the connection is no longer applied
    apply_conn(c, code="awaiting_local_trust")
    pend_conn, _, _ = make_conn(c)
    assert c.post(pend_conn).status_code == 202
    assert c.post(c.make("ssh_login")[0]).status_code == 202
    leased = c.next().json()
    assert leased["kind"] == "olt_connection"                                                                    # the oldest one is now in flight (DISPATCHED); the credential still waits (PENDING)
    for kw in ({"mgmt_protocol": "telnet"}, {"mgmt_port": 2201}, {"host_key_sha256": "SHA256:" + "C" * 43}, {"mgmt_address": "10.77.88.101"}):   # what is leased to the Edge cannot be recalled: the change waits (Codex r1)
        r = c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json=kw)
        assert (r.status_code, r.json()["detail"]) == (409, "delivery_in_flight"), kw
    assert state(c.migrated, c.olt).mgmt_protocol == "ssh" and c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"label": "ok"}).status_code == 200   # nothing was half-applied
    assert c.result(leased["id"], leased["lease_token"]).status_code == 204                                      # the Edge answers: the lease is over...
    r = c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_protocol": "telnet"})                 # ...and now the PENDING credential is cancelled with the rest
    assert r.status_code == 200, r.text
    assert (r.json()["connection"]["protocol"], r.json()["connection"]["port"], r.json()["connection"]["host_key_sha256"], r.json()["connection"]["ssh_mode"], r.json()["connection"]["legacy_ssh"],
            r.json()["connection"]["trust_state"], r.json()["connection"]["applied"], r.json()["readiness"]["stage"]) == ("telnet", 23, None, None, False, "none", False, "telnet_inventory")
    with c.migrated.begin() as conn:
        left = conn.execute(text("SELECT status, code, has_blob FROM olt_secret_deliveries WHERE olt_id = :o AND status IN ('PENDING', 'DISPATCHED')"), {"o": c.olt}).all()
        cancelled = conn.execute(text("SELECT count(*) FROM olt_secret_deliveries WHERE olt_id = :o AND code = 'protocol_changed' AND NOT has_blob AND status = 'CANCELLED'"), {"o": c.olt}).scalar()
    assert left == [] and cancelled >= 1
    for kind in ("olt_connection", "ssh_login", "snmp_community"):                                               # and from now on nothing is queued, whatever the kind
        body = make_conn(c)[0] if kind == "olt_connection" else c.make(kind)[0]
        r = c.post(body)
        assert (r.status_code, r.json()["detail"]) == (422, "protocol_not_supported"), kind
    assert c.next().status_code == 204
    # telnet -> ssh: back to port 22, the fingerprint is typed again
    r = c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_protocol": "ssh", "host_key_sha256": HK})
    assert r.status_code == 200 and r.json()["connection"]["port"] == 22 and r.json()["connection"]["ssh_mode"] == "exec" and r.json()["connection"]["host_key_sha256"] == HK
    assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_protocol": "telnet", "host_key_sha256": HK}).json()["detail"] == "telnet_has_no_ssh_fields"
    assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_transport": "snmp", "snmp_version": "v3"}).json()["detail"] == "snmp_transport_needs_v2c"
    assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"edge_trust_state": "trusted"}).status_code == 422
    assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_protocol": None}).json()["connection"]["port"] is None


def test_the_audit_of_an_edit_carries_field_names_and_counts_only(ctx):
    c = ctx
    c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_address": ADDR, "mgmt_protocol": "ssh", "host_key_sha256": HK})
    assert c.post(make_conn(c)[0]).status_code == 202
    c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_protocol": "telnet"})
    with c.migrated.begin() as conn:
        rows = conn.execute(text("SELECT evidence_redacted FROM audit_log WHERE action = 'fleet.olt.updated' AND target_id = :o ORDER BY created_at"), {"o": str(c.olt)}).all()
    assert [r[0] for r in rows][-1] == {"fields": ["mgmt_protocol"], "cancelled_deliveries": 1}
    assert ADDR not in json.dumps([r[0] for r in rows]) and HK not in json.dumps([r[0] for r in rows])


# ------------------------------------------------------------------ the kind olt_connection: permission, flag, channel
def test_the_connection_kind_has_its_own_permission_and_flag_apart_from_the_credentials(client, seed, inv, migrated):
    c = Ctx(client, seed, inv, migrated)
    reach(migrated, c.olt)
    conn_body = make_conn(c)[0]
    cred_body = c.make("ssh_login")[0]
    _flags(migrated, seed["A"], fleet_secrets=True, fleet_provision=False)
    r = c.post(conn_body)
    assert (r.status_code, r.json()["detail"]) == (403, "feature_disabled")                                      # credentials on, connection off
    assert c.post(cred_body).status_code == 202
    _flags(migrated, seed["A"], fleet_secrets=False, fleet_provision=True)
    r = c.post(c.make("snmp_community")[0])
    assert (r.status_code, r.json()["detail"]) == (403, "feature_disabled")                                      # connection on, credentials off
    assert c.post(conn_body).status_code == 202
    assert c.client.get(f"/v1/fleet/edges/{c.edge}/seal-key", headers=c.h).status_code == 200                    # the key of the Edge is readable with either flag
    assert [i["kind"] for i in c.client.get(f"/v1/fleet/olts/{c.olt}/secret-deliveries", headers=c.h).json()["items"]] == ["olt_connection"]   # the list shows only the kinds the flags open
    _flags(migrated, seed["A"], fleet_secrets=False, fleet_provision=False)
    for method, path, body in (("GET", f"/v1/fleet/edges/{c.edge}/seal-key", None), ("GET", f"/v1/fleet/olts/{c.olt}/secret-deliveries", None), ("POST", f"/v1/fleet/olts/{c.olt}/secret-deliveries", {"garbage": 1}),
                               ("POST", f"/v1/fleet/edges/{c.edge}/seal-key/confirm", {"key_id": "0" * 16, "fingerprint": "x"})):
        r = c.client.request(method, path, headers=c.h, json=body)
        assert (r.status_code, r.json()["detail"]) == (403, "feature_disabled"), path                           # both off: closed whatever was sent
    _flags(migrated, seed["A"], fleet_provision=True)
    hb = hdr(client, "carol", seed, "A")                                                                          # carol is an auditor in A: no fleet permission at all
    assert c.post(make_conn(c)[0], headers=hb).status_code == 403
    hd = hdr(client, "dave", seed, "A")
    assert c.post(make_conn(c)[0], headers=hd).status_code == 403
    _flags(migrated, seed["B"], fleet_provision=True, fleet_secrets=True, fleet_manager=True)
    hcb = hdr(client, "carol", seed, "B")                                                                         # an engineer: fleet:manage, but neither secrets nor provision
    assert c.client.get(f"/v1/fleet/edges/{inv['b1']['edge']}/seal-key", headers=hcb).status_code == 403
    assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=hcb, json={"label": "x"}).status_code == 404       # (and another tenant's OLT is not even found)
    assert c.post(make_conn(c)[0], headers=c.ah).status_code == 403                                              # the Edge is not a person


def test_the_edge_receives_the_connection_with_the_kind_in_the_aad_and_a_signature_and_only_when_its_flag_is_on(ctx):
    c = ctx
    reach(c.migrated, c.olt)
    _flags(c.migrated, c.tenant, fleet_provision=False)
    cred, _ = c.make("ssh_login")
    assert c.post(cred).status_code == 202
    _flags(c.migrated, c.tenant, fleet_provision=True)
    conn_body, aad, plain = make_conn(c)
    assert c.post(conn_body).status_code == 202
    _flags(c.migrated, c.tenant, fleet_provision=False, fleet_secrets=True)
    n = c.next().json()                                                                                           # the connection is older? no: the credential is; either way only an OPEN kind is leased
    assert n["kind"] == "ssh_login"
    assert c.result(n["id"], n["lease_token"]).status_code == 204
    assert c.next().status_code == 204                                                                            # the connection waits: its flag is off
    _flags(c.migrated, c.tenant, fleet_provision=True)
    d = c.next().json()
    assert d["kind"] == "olt_connection" and set(d) == {"id", "lease_token", "olt_name", "kind", "key_id", "expires_at", "sealed", "signature"}
    blob = olt_secrets.b64url_decode(d["sealed"])
    my_aad = olt_secrets.aad(tenant_id=c.tenant, edge_id=c.edge, olt_name=d["olt_name"], kind=d["kind"], delivery_id=d["id"], key_id_=d["key_id"], expires_at_unix=d["expires_at"])
    assert my_aad == aad and my_aad.split("\n")[4] == "olt_connection"
    Ed25519PrivateKey.from_private_bytes(base64.b64decode(JOB_SEED_B64)).public_key().verify(olt_secrets.b64url_decode(d["signature"]),
                                                                                              f"fibercore-delivery-v1\n{my_aad}\n{hashlib.sha256(blob).hexdigest()}".encode())
    assert json.loads(H.open_blob(c.priv, blob, my_aad, d["key_id"])) == plain                                    # the exact clear text of ADR-0046 D4
    with pytest.raises(InvalidTag):   # the same blob under the AAD of a credential kind does not open: the kind is authenticated
        H.open_blob(c.priv, blob, my_aad.replace("olt_connection", "ssh_login"), d["key_id"])
    _flags(c.migrated, c.tenant, fleet_provision=False, fleet_secrets=False)
    assert c.next().status_code == 204                                                                            # the leased one is not handed out again while its flag is off
    _flags(c.migrated, c.tenant, fleet_provision=True)
    assert c.next().json()["lease_token"] == d["lease_token"]                                                     # flag back: the same lease, as a retry would


def test_telnet_gets_no_delivery_of_any_kind_whatever_the_state_of_the_key_or_the_flags(ctx):
    c = ctx
    reach(c.migrated, c.olt, mgmt_protocol="telnet", mgmt_port=23, host_key_sha256=None, ssh_mode=None)
    for kind in ("olt_connection", "ssh_login", "snmp_community"):
        body = make_conn(c)[0] if kind == "olt_connection" else c.make(kind)[0]
        r = c.post(body)
        assert (r.status_code, r.json()["detail"]) == (422, "protocol_not_supported"), kind
        assert "SENTINEL" not in r.text
    with c.migrated.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM olt_secret_deliveries WHERE olt_id = :o"), {"o": c.olt}).scalar() == 0
    assert c.next().status_code == 204


# ------------------------------------------------------------------ the Edge's result and its state report
def test_the_result_of_a_connection_may_carry_awaiting_local_trust_and_no_other_code(ctx):
    c = ctx
    reach(c.migrated, c.olt)

    def lease(kind="olt_connection"):
        body = make_conn(c)[0] if kind == "olt_connection" else c.make(kind)[0]
        assert c.post(body).status_code == 202
        n = c.next().json()
        assert n["kind"] == kind
        return n
    n = lease("ssh_login")
    assert c.result(n["id"], n["lease_token"], code="awaiting_local_trust").status_code == 422                    # that code is about a connection only
    assert c.result(n["id"], n["lease_token"]).status_code == 204
    n = lease()
    for bad in ("trusted", "write_failed", "stale", "bogus"):
        assert c.result(n["id"], n["lease_token"], code=bad).status_code == 422, bad                              # `applied` accepts nothing but awaiting_local_trust
    assert c.result(n["id"], n["lease_token"], outcome="failed", code="awaiting_local_trust").status_code == 422   # and it is not a failure
    assert c.result(n["id"], n["lease_token"], outcome="failed").status_code == 422                                # a failure needs its code
    assert state(c.migrated, c.olt).edge_trust_state == "none"
    assert c.result(n["id"], n["lease_token"], code="awaiting_local_trust").status_code == 204
    st = state(c.migrated, c.olt)
    assert (st.edge_trust_state, st.conn_applied_at is not None) == ("awaiting_local_trust", True)
    assert c.result(n["id"], n["lease_token"], code="awaiting_local_trust").status_code == 204                    # the same result again: idempotent
    assert c.result(n["id"], n["lease_token"]).status_code == 409                                                  # a different one: conflict
    row = c.client.get(f"/v1/fleet/olts/{c.olt}/secret-deliveries", headers=c.h).json()["items"][0]
    assert (row["kind"], row["status"], row["code"]) == ("olt_connection", "APPLIED", "awaiting_local_trust")
    n = lease()                                                                                                    # a plain `applied` (the Edge already trusted this exact connection): the record is applied, trust is the Edge's report
    assert c.result(n["id"], n["lease_token"]).status_code == 204
    assert state(c.migrated, c.olt).edge_trust_state == "awaiting_local_trust"
    for code in olt_secrets.RESULT_CODES:                                                                          # every failure code of ADR-0045 + ADR-0046 D5 is accepted, with the blob gone
        n = lease()
        assert c.result(n["id"], n["lease_token"], outcome="failed", code=code).status_code == 204, code
        r = c.row(n["id"])
        assert (r.status, r.code, r.has_blob) == ("FAILED", code, False)
    reach(c.migrated, c.olt, mgmt_port=2200)
    assert state(c.migrated, c.olt).edge_trust_state == "none"                                                     # (and the way of reaching it changing demotes it, as proved above)


def test_the_managed_state_report_touches_only_the_calling_edges_own_olts_and_reveals_nothing_else(ctx, client, seed, inv, migrated):
    c = ctx
    reach(migrated, c.olt)
    apply_conn(c, code="awaiting_local_trust")
    with migrated.begin() as conn:
        olt_a2 = conn.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level, mgmt_protocol, mgmt_port, conn_applied_at) VALUES (:t,:e,'SEC-OLT-A2','huawei','identified','ssh',22,now()) RETURNING id"),
                              {"t": seed["A"], "e": inv["a2"]["edge"]}).scalar()
        olt_b = conn.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level, mgmt_protocol, mgmt_port, conn_applied_at) VALUES (:t,:e,'SEC-OLT-B1','huawei','identified','ssh',22,now()) RETURNING id"),
                             {"t": seed["B"], "e": inv["b1"]["edge"]}).scalar()
        olt_tel = conn.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level, mgmt_protocol, mgmt_port) VALUES (:t,:e,'SEC-OLT-TEL','huawei','identified','telnet',23) RETURNING id"),
                               {"t": seed["A"], "e": c.edge}).scalar()
        olt_new = conn.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level, mgmt_protocol, mgmt_port) VALUES (:t,:e,'SEC-OLT-NEW','huawei','identified','ssh',22) RETURNING id"),
                               {"t": seed["A"], "e": c.edge}).scalar()
    items = [{"cloud_id": str(c.olt), "state": "trusted"}, {"cloud_id": str(olt_a2), "state": "trusted"}, {"cloud_id": str(olt_b), "state": "trusted"}, {"cloud_id": str(uuid.uuid4()), "state": "trusted"},
             {"cloud_id": str(olt_tel), "state": "trusted"}, {"cloud_id": str(olt_new), "state": "trusted"}]
    r = report(c, items)
    assert (r.status_code, r.json()) == (200, {"updated": 1, "ignored": 5})                                        # own+applied only; another Edge's, another tenant's, unknown, Telnet, not-applied: all just `ignored`
    assert state(migrated, c.olt).edge_trust_state == "trusted"
    for other in (olt_a2, olt_b, olt_tel, olt_new):
        assert state(migrated, other).edge_trust_state == "none"
    # the answer for an OLT of ANOTHER tenant, another Edge and one that does not exist is the same: no way to tell them apart
    answers = {json.dumps(report(c, [{"cloud_id": str(x), "state": "trusted"}]).json()) for x in (olt_a2, olt_b, uuid.uuid4())}
    assert answers == {'{"updated": 0, "ignored": 1}'}
    assert report(c, [{"cloud_id": str(c.olt), "state": "trusted"}]).json() == {"updated": 1, "ignored": 0}        # the same state again: nothing changes (counted, not audited again)
    with migrated.begin() as conn:
        n_audit = conn.execute(text("SELECT count(*) FROM audit_log WHERE action = 'fleet.olt.trust_state' AND target_id = :o"), {"o": str(c.olt)}).scalar()
        ev = conn.execute(text("SELECT evidence_redacted FROM audit_log WHERE action = 'fleet.olt.trust_state' AND target_id = :o"), {"o": str(c.olt)}).scalar()
    assert n_audit == 1 and ev == {"state": "trusted"}
    assert report(c, [{"cloud_id": str(c.olt), "state": "awaiting_local_trust"}]).json() == {"updated": 1, "ignored": 0}   # the Edge may also go back to awaiting (a changed fingerprint at its side)
    assert state(migrated, c.olt).edge_trust_state == "awaiting_local_trust"
    assert report(c, [{"cloud_id": str(c.olt), "state": "removed"}]).json() == {"updated": 1, "ignored": 0}
    st = state(migrated, c.olt)
    assert (st.edge_trust_state, st.conn_applied_at) == ("none", None)                                             # removed: back to "not delivered"
    assert view(c)["readiness"]["stage"] == "registered"
    assert report(c, []).json() == {"updated": 0, "ignored": 0}
    # shape and who may call
    assert report(c, [{"cloud_id": str(c.olt), "state": "trusted"}] * 65).status_code == 422                       # at most 64 items
    assert report(c, [{"cloud_id": str(c.olt), "state": "trusted"}] * 64).status_code == 200
    for bad in ([{"cloud_id": str(c.olt), "state": "none"}], [{"cloud_id": "x", "state": "trusted"}], [{"cloud_id": str(c.olt), "state": "trusted", "extra": 1}]):
        assert report(c, bad).status_code == 422, bad
    assert client.post("/v1/edge/managed-olts/state", headers=c.ah, json={"items": [], "x": 1}).status_code == 422
    assert report(c, [], headers=c.h).status_code == 403                                                           # a person is not an Edge
    assert client.post("/v1/edge/managed-olts/state", json={"items": []}).status_code == 401
    assert report(c, [{"cloud_id": str(olt_b), "state": "trusted"}], headers=agent(client, inv, "b1")).json() == {"updated": 1, "ignored": 0}   # tenant B's Edge reports ITS OLT: fine
    assert state(migrated, olt_b).edge_trust_state == "trusted" and state(migrated, c.olt).edge_trust_state == "none"
    routes = [r for r in _routes() if r.path == "/v1/edge/managed-olts/state"]
    assert routes and any(d.call is deps.edge_ingest_limit for d in routes[0].dependant.dependencies)              # the intake limit applies, like every Edge intake route
    assert "edge_ingest_limit" in inspect.getsource(deps) and "jobs:execute" in {getattr(d.call, "rbac_permission", None) for d in routes[0].dependant.dependencies}


# ------------------------------------------------------------------ two tenants
def test_rls_a_tenant_never_sees_or_changes_the_connection_of_another_tenants_olt(ctx, client, seed, inv, migrated, app_url):
    c = ctx
    reach(migrated, c.olt)
    apply_conn(c, code="awaiting_local_trust")
    _flags(migrated, seed["B"], fleet_manager=True, fleet_secrets=True, fleet_provision=True)
    hb = hdr(client, "bob", seed, "B")
    assert client.get(f"/v1/fleet/olts/{c.olt}", headers=hb).status_code == 404
    assert str(c.olt) not in client.get("/v1/fleet/olts", headers=hb).text
    for method, path, body in (("PATCH", f"/v1/fleet/olts/{c.olt}", {"mgmt_protocol": "telnet"}), ("POST", f"/v1/fleet/olts/{c.olt}/secret-deliveries", make_conn(c)[0]),
                               ("GET", f"/v1/fleet/olts/{c.olt}/secret-deliveries", None), ("GET", f"/v1/fleet/edges/{c.edge}/seal-key", None)):
        assert client.request(method, path, headers=hb, json=body).status_code == 404, path
    # B's Edge cannot report on A's OLT, even knowing its id; A's row is untouched
    r = client.post("/v1/edge/managed-olts/state", headers=agent(client, inv, "b1"), json={"items": [{"cloud_id": str(c.olt), "state": "removed"}]})
    assert r.json() == {"updated": 0, "ignored": 1}
    st = state(migrated, c.olt)
    assert (st.edge_trust_state, st.conn_applied_at is not None, st.mgmt_protocol) == ("awaiting_local_trust", True, "ssh")
    # B has its own, independent fields
    rb = client.post("/v1/fleet/olts", headers=hb, json={"name": "CTR-B-1", "edge_id": str(inv["b1"]["edge"]), "vendor": "zte", "mgmt_protocol": "ssh", "mgmt_port": 2200, "host_key_sha256": HK2})
    assert rb.status_code == 201 and rb.json()["connection"]["port"] == 2200 and rb.json()["connection"]["trust_state"] == "none"
    assert view(c)["connection"]["port"] == 22
    eng = _sqla(app_url)
    try:
        with eng.begin() as conn:   # under B's session the database itself shows nothing of A's row, and the function ignores it
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
            assert conn.execute(text("SELECT count(*) FROM olts WHERE id = :o"), {"o": c.olt}).scalar() == 0
            assert conn.execute(text("SELECT app_olt_edge_report(:o, :e, 'removed')"), {"o": c.olt, "e": c.edge}).scalar() == "ignored"
            assert conn.execute(text("UPDATE olts SET mgmt_port = 1 WHERE id = :o"), {"o": c.olt}).rowcount == 0
    finally:
        eng.dispose()
    assert state(migrated, c.olt).edge_trust_state == "awaiting_local_trust"


def test_nothing_secret_and_no_full_address_in_any_response_log_or_audit(ctx, caplog):
    c = ctx
    caplog.set_level(logging.DEBUG)
    seen = []
    r = c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_address": ADDR, "mgmt_protocol": "ssh", "host_key_sha256": HK})
    seen.append(r.text)
    body, _, _ = make_conn(c)
    r = c.post(body)
    seen += [r.text, c.client.get(f"/v1/fleet/olts/{c.olt}/secret-deliveries", headers=c.h).text, c.client.get("/v1/fleet/olts", headers=c.h).text, view(c).__repr__()]
    n = c.next().json()
    c.result(n["id"], n["lease_token"], code="awaiting_local_trust")
    seen += [report(c, [{"cloud_id": str(c.olt), "state": "trusted"}]).text, c.client.get(f"/v1/fleet/olts/{c.olt}", headers=c.h).text]
    with c.migrated.begin() as conn:
        audit = json.dumps([[a, e] for a, e in conn.execute(text("SELECT action, evidence_redacted FROM audit_log WHERE action LIKE 'fleet.%' AND (target_id = :o OR evidence_redacted::text LIKE '%' || :o || '%')"), {"o": str(c.olt)}).all()])
    everything = "".join(seen) + caplog.text + audit
    raw_b64 = base64.b64encode(olt_secrets.b64url_decode(body["sealed"])).decode()
    for needle in (ADDR, body["sealed"], raw_b64, body["sealed"][20:60]):
        assert needle not in everything, needle
    assert HK not in audit and HK not in caplog.text                                                               # the fingerprint is public and may be READ back (it is in the OLT view), but is not logged
    assert HK in view(c).__repr__() and "10.77.•.•" in view(c).__repr__()
    assert "SENTINEL-PW" not in everything and "SENTINEL-USER" not in everything


def test_a_credential_in_flight_blocks_the_switch_to_telnet_but_not_a_change_of_the_connection(ctx):
    c = ctx
    reach(c.migrated, c.olt)
    assert c.post(c.make("ssh_login")[0]).status_code == 202
    n = c.next().json()
    assert n["kind"] == "ssh_login"
    assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_port": 2202}).status_code == 200     # a credential is not tied to how the OLT is reached
    r = c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_protocol": "telnet"})
    assert (r.status_code, r.json()["detail"]) == (409, "delivery_in_flight")
    c.lapse(n["id"])                                                                                                # a lease that ran out is not in flight any more
    assert c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_protocol": "telnet"}).status_code == 200


def test_a_change_of_the_connection_and_the_dispatch_of_its_delivery_never_interleave(ctx):
    """Real concurrency: PATCH (holds the OLT row) against `next` (locks the OLT row FOR SHARE before the delivery). Either the dispatch came first (the PATCH is then refused: 409) or the PATCH committed first
    (the delivery is CANCELLED and nothing is handed out: 204). Never a delivery handed to the Edge AND cancelled by an accepted change."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    c = ctx
    reach(c.migrated, c.olt)
    outcomes = set()
    for i in range(12):
        body, _, _ = make_conn(c)
        assert c.post(body).status_code == 202
        barrier = threading.Barrier(2)

        def patch(b=barrier, port=3000 + i):
            b.wait()
            return c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"mgmt_port": port})

        def nxt(b=barrier):
            b.wait()
            return c.next()
        with ThreadPoolExecutor(2) as ex:
            fp, fn = ex.submit(patch), ex.submit(nxt)
            rp, rn = fp.result(), fn.result()
        row = c.row(body["delivery_id"])
        if rp.status_code == 200:
            outcomes.add("patch_first")
            assert rn.status_code == 204 and (row.status, row.has_blob) == ("CANCELLED", False), (rn.status_code, row.status)
        else:
            outcomes.add("dispatch_first")
            assert (rp.status_code, rp.json()["detail"]) == (409, "delivery_in_flight") and rn.status_code == 200 and row.status == "DISPATCHED"
            assert c.result(rn.json()["id"], rn.json()["lease_token"]).status_code == 204
    assert outcomes                                                                                                 # (which of the two wins is the scheduler's; both are consistent)


def test_result_next_patch_and_create_take_the_olt_before_the_delivery_so_they_never_deadlock(ctx):
    """Codex r2: `result` of an applied connection writes the OLT row. Four writers racing for the same OLT must all finish without a 5xx (a deadlock would abort one of them after ~1 s)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    c = ctx
    reach(c.migrated, c.olt)
    for i in range(10):
        assert c.post(make_conn(c)[0]).status_code == 202
        n = c.next().json()
        assert n["kind"] == "olt_connection"
        assert c.post(make_conn(c)[0]).status_code == 202                                                          # one more waiting: `next` has something to dispatch next to the result
        barrier = threading.Barrier(4)

        def run(fn, b=barrier):
            b.wait()
            return fn()
        jobs = (lambda n=n: c.result(n["id"], n["lease_token"], code="awaiting_local_trust"),
                lambda: c.next(),
                lambda i=i: c.client.patch(f"/v1/fleet/olts/{c.olt}", headers=c.h, json={"label": f"L{i}"}),
                lambda: c.post(make_conn(c)[0]))
        with ThreadPoolExecutor(4) as ex:
            res = [f.result() for f in [ex.submit(run, j) for j in jobs]]
        assert [r.status_code for r in res][0] in (204, 409) and all(r.status_code < 500 for r in res), [r.status_code for r in res]
        with c.migrated.begin() as conn:   # the board is clean for the next round
            conn.execute(text("UPDATE olt_secret_deliveries SET status = 'CANCELLED', sealed = NULL WHERE olt_id = :o AND status IN ('PENDING', 'DISPATCHED')"), {"o": c.olt})


def test_a_connection_needs_the_protocol_registered_as_ssh_while_the_credentials_of_an_older_registration_still_go(ctx):
    c = ctx                                                                                                         # the OLT of `ctx` has no protocol at all (an older-style registration)
    r = c.post(make_conn(c)[0])
    assert (r.status_code, r.json()["detail"]) == (422, "protocol_required")
    with c.migrated.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM olt_secret_deliveries WHERE olt_id = :o"), {"o": c.olt}).scalar() == 0
    assert c.post(c.make("ssh_login")[0]).status_code == 202                                                       # an OLT written in the Edge's own config keeps receiving credentials (ADR-0045)
    reach(c.migrated, c.olt)
    assert c.post(make_conn(c)[0]).status_code == 202


def test_the_connection_test_is_no_longer_refused_for_telnet_and_a_test_before_the_connection_was_applied_is_not_readiness(ctx):
    c = ctx
    reach(c.migrated, c.olt, mgmt_protocol="telnet", mgmt_port=23, host_key_sha256=None, ssh_mode=None)
    r = c.client.post(f"/v1/fleet/olts/{c.olt}/connection-test", headers=c.h)
    assert r.json().get("detail") != "protocol_not_supported"   # ADR-0053: the Edge reads a Telnet OLT through its own static entry; the other gates (flag, channel) still decide
    reach(c.migrated, c.olt)
    with c.migrated.begin() as conn:   # an identity read by a job BEFORE the connection was ever applied
        conn.execute(text("INSERT INTO olt_query_latest (tenant_id, olt_id, query_id, params_key, data, observed_at, asked_at, owner_epoch, source, version) "
                          "SELECT tenant_id, id, 'olt.connection', '', CAST(:d AS jsonb), now(), now(), owner_epoch, 'job', 1 FROM olts WHERE id = :o"),
                     {"o": c.olt, "d": json.dumps({"product": "MA5608T", "version": "R015", "patch": "SPC100", "uptime_seconds": 1})})
    assert view(c)["readiness"]["steps"]["tested"] is False                                                        # not applied: an old reading is not "tested"
    apply_conn(c, code="awaiting_local_trust")
    assert view(c)["readiness"]["steps"]["tested"] is False                                                        # the reading predates the applied connection
