"""Capability Registry (ADR-0019, FC22-002): unknown by default, per profile, per tenant, read-only for the app, never opens a write."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.jobs import OPERATIONS
from tests.conftest import _now, agent, hdr, login, snap


@pytest.fixture(autouse=True, scope="module")
def _clean_up_after_the_module(migrated):
    """This module creates CPEs/OLTs/registry rows in the shared tenants; later modules (and `inv`-based counts) must not see them."""
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM device_capabilities"))
        c.execute(text("DELETE FROM cpe_protocol_bindings WHERE cpe_id IN (SELECT id FROM cpes WHERE canonical_serial LIKE 'CAP%')"))
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'CAP%'"))
        c.execute(text("DELETE FROM onus WHERE serial LIKE 'CAP-%'"))
        c.execute(text("DELETE FROM pon_ports WHERE olt_id IN (SELECT id FROM olts WHERE name LIKE 'OLT-CAP-%')"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'OLT-CAP-%'"))


def _olt(client, inv, name, firmware="R018"):
    body = snap(inv, name=name, firmware=firmware, onus=[{"serial": f"CAP-{name}", "pon_path": "0/1/0", "status": "online"}])
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202


def _olt_id(client, seed, name):
    return next(o["id"] for o in client.get("/v1/olts", headers=hdr(client, "alice", seed, "A")).json() if o["name"] == name)


def _cpe(client, inv, serial, ext, vendor="ACME", model="G3000", firmware="1.0.3", key="a1", obs=None):
    body = {"edge_id": str(inv[key]["edge"]), "observed_at": obs or _now(), "cpes": [
        {"canonical_serial": serial, "vendor": vendor, "model": model, "firmware": firmware,
         "binding": {"protocol": "tr069", "external_id": ext, "connector_id": f"c-cap-{key}"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, key), json=body).status_code == 202


def _cpe_id(client, seed, serial, who="alice", tenant="A"):
    return next(c["id"] for c in client.get("/v1/cpes", headers=hdr(client, who, seed, tenant)).json() if c["canonical_serial"] == serial)


def _set(migrated, tenant, **kw):
    row = {"vendor": "ACME", "model": "G3000", "firmware": "1.0.3", "protocol": "tr069", "operation": "refresh", "status": "supported",
           "certification": "observed", "verified_at": "2026-10-29T12:00:00+00:00", "evidence_ref": "lab-run-1", **kw}
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, "
                       "verified_at, evidence_ref) VALUES (:t,:vendor,:model,:firmware,:protocol,:operation,:status,:certification,"
                       ":verified_at,:evidence_ref)"), {"t": tenant, **row})


def test_unknown_by_default_for_every_catalog_operation(client, seed, inv):
    _cpe(client, inv, "CAPDEF-0001", "cap-def-1", model="UNREG")
    caps = client.get(f"/v1/cpes/{_cpe_id(client, seed, 'CAPDEF-0001')}/capabilities", headers=hdr(client, "alice", seed, "A")).json()
    cpe_ops = {n for n, o in OPERATIONS.items() if o.target == "cpe"}
    assert {(c["name"], c["protocol"]) for c in caps} == {(n, p) for n in cpe_ops for p in ("tr069", "tr369")}  # exactly the job engine's ops
    assert all(c["status"] == "unknown" and c["certification"] == "identified" and c["evidence_ref"] is None for c in caps)
    assert all((c["blocked_reason"] == "operation_not_homologated") == c["writes"] for c in caps)


def test_profile_match_is_exact_on_firmware_and_case_insensitive_on_vendor_model(client, seed, inv, migrated):
    _cpe(client, inv, "CAPMATCH-01", "cap-m-1", vendor="Acme", model="g3000", firmware="1.0.3")
    _cpe(client, inv, "CAPMATCH-02", "cap-m-2", vendor="Acme", model="g3000", firmware="1.0.4")
    _cpe(client, inv, "CAPMATCH-03", "cap-m-3", vendor="Acme", model="g3000", firmware=None)
    _set(migrated, seed["A"], vendor="ACME", model="G3000", firmware="1.0.3", operation="refresh")
    h = hdr(client, "alice", seed, "A")
    got = lambda s: {(c["name"], c["protocol"]): c for c in client.get(f"/v1/cpes/{_cpe_id(client, seed, s)}/capabilities", headers=h).json()}  # noqa: E731
    hit = got("CAPMATCH-01")[("refresh", "tr069")]
    assert (hit["status"], hit["certification"], hit["evidence_ref"]) == ("supported", "observed", "lab-run-1") and hit["verified_at"]
    assert got("CAPMATCH-01")[("refresh", "tr369")]["status"] == "unknown"  # other protocol: not covered
    assert got("CAPMATCH-02")[("refresh", "tr069")]["status"] == "unknown"  # another firmware: not covered
    assert got("CAPMATCH-03")[("refresh", "tr069")]["status"] == "unknown"  # firmware not reported: never guessed


def test_a_certified_row_never_opens_a_write(client, seed, inv, migrated):
    _cpe(client, inv, "CAPWRITE-01", "cap-w-1", vendor="WriteCo", model="W1", firmware="9.9")
    _set(migrated, seed["A"], vendor="WriteCo", model="W1", firmware="9.9", operation="set_wifi_ssid", certification="certified")
    caps = client.get(f"/v1/cpes/{_cpe_id(client, seed, 'CAPWRITE-01')}/capabilities", headers=hdr(client, "alice", seed, "A")).json()
    c = next(x for x in caps if x["name"] == "set_wifi_ssid" and x["protocol"] == "tr069")
    assert c["certification"] == "certified" and c["status"] == "supported"
    assert c["writes"] is True and c["blocked_reason"] == "operation_not_homologated"  # the job engine's gate still decides


def test_olt_capabilities_use_the_olt_profile_and_olt_operations(client, seed, inv, migrated):
    _olt(client, inv, "OLT-CAP-1")
    _set(migrated, seed["A"], vendor="huawei", model="MA5800-X7", firmware="R018", protocol="olt", operation="collect", certification="observed")
    caps = client.get(f"/v1/olts/{_olt_id(client, seed, 'OLT-CAP-1')}/capabilities", headers=hdr(client, "alice", seed, "A")).json()
    assert {(c["name"], c["protocol"]) for c in caps} == {("collect", "olt"), ("provision_onu", "olt"), ("olt_query", "olt")}
    by = {c["name"]: c for c in caps}
    assert by["collect"]["status"] == "supported" and by["provision_onu"]["status"] == "unknown"
    assert by["provision_onu"]["blocked_reason"] == "operation_not_homologated" and by["collect"]["blocked_reason"] is None


def test_tenants_are_isolated_and_permissions_enforced(client, seed, inv, migrated):
    _cpe(client, inv, "CAPISO-0001", "cap-i-1", vendor="IsoCo", model="I1", firmware="1")
    _set(migrated, seed["A"], vendor="IsoCo", model="I1", firmware="1", operation="refresh")
    cid = _cpe_id(client, seed, "CAPISO-0001")
    assert client.get(f"/v1/cpes/{cid}/capabilities", headers=hdr(client, "bob", seed, "B")).status_code == 404  # other tenant's CPE
    # a row of tenant B for the same profile does not leak into A, and A's does not show in B
    _cpe(client, inv, "CAPISO-0001", "cap-i-b1", vendor="IsoCo", model="I1", firmware="1", key="b1")
    bid = _cpe_id(client, seed, "CAPISO-0001", who="bob", tenant="B")
    assert all(c["status"] == "unknown" for c in client.get(f"/v1/cpes/{bid}/capabilities", headers=hdr(client, "bob", seed, "B")).json())
    assert client.get(f"/v1/cpes/{cid}/capabilities", headers=hdr(client, "dave", seed, "A")).status_code == 200  # noc_n1: inventory:read
    assert client.get(f"/v1/cpes/{cid}/capabilities", headers={**login(client, "carol"), "X-Workspace-ID": str(seed["A"])}).status_code == 403  # auditor
    assert client.get(f"/v1/cpes/{cid}/capabilities", headers=agent(client, inv, "a1")).status_code == 403  # agents never read
    assert client.get(f"/v1/cpes/{cid}/capabilities").status_code == 401
    assert client.get("/v1/cpes/00000000-0000-0000-0000-000000000000/capabilities", headers=hdr(client, "alice", seed, "A")).status_code == 404
    assert client.get("/v1/olts/not-a-uuid/capabilities", headers=hdr(client, "alice", seed, "A")).status_code == 422


def test_database_refuses_unevidenced_claims_and_the_app_role_cannot_write(client, seed, migrated):
    for kw in ({"certification": "certified", "evidence_ref": None}, {"certification": "observed", "verified_at": None},
               {"certification": "identified", "status": "supported", "evidence_ref": None, "verified_at": None},  # a bare "supported"
               {"certification": "identified", "status": "unsupported", "evidence_ref": "x", "verified_at": None}):
        with pytest.raises(DBAPIError):
            _set(migrated, seed["A"], vendor="NoEvidence", **kw)
    with pytest.raises(DBAPIError):
        _set(migrated, seed["A"], vendor="BadOp", operation="Not A Valid Op!")
    from app.core.db import get_engine, scoped_connection
    with pytest.raises(DBAPIError), scoped_connection(get_engine(), tenant_id=seed["A"]) as c:  # the runtime role has SELECT only
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation) "
                        "VALUES (:t,'x','y','z','olt','collect')"), {"t": seed["A"]})


def test_cli_capability_set_requires_evidence_validates_the_catalog_and_emits_an_event(seed, migrated, admin_url, monkeypatch):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(seed["A"])
    base = [t, "CliCo", "C1", "2.0", "tr069", "refresh", "supported"]
    with pytest.raises(SystemExit, match="requires --evidence"):
        cli.main(["capability-set", *base, "certified"])
    with pytest.raises(SystemExit, match="requires --evidence"):  # "supported" is a claim too, even at the lowest certification
        cli.main(["capability-set", *base, "identified"])
    with pytest.raises(SystemExit, match="unknown operation"):
        cli.main(["capability-set", t, "CliCo", "C1", "2.0", "tr069", "invented_op", "unknown", "identified"])
    with pytest.raises(SystemExit, match="not catalogued"):  # OLT operation over a CPE protocol, and the other way round
        cli.main(["capability-set", t, "CliCo", "C1", "2.0", "tr069", "collect", "unknown", "identified"])
    with pytest.raises(SystemExit, match="not catalogued"):
        cli.main(["capability-set", t, "CliCo", "C1", "2.0", "olt", "set_wifi_ssid", "unknown", "identified"])
    cli.main(["capability-set", t, "CliCo", "C1", "2.0", "tr369", "refresh", "unknown", "identified"])  # a valid pair on the other CPE protocol
    cli.main(["capability-set", *base, "observed", "--evidence", "lab-cli-1", "--verified-at", "2026-10-29T12:00:00+00:00"])
    cli.main(["capability-set", *base, "certified", "--evidence", "lab-cli-2", "--verified-at", "2026-10-29T13:00:00+00:00"])  # upsert
    with migrated.begin() as c:
        rows = c.execute(text("SELECT certification, evidence_ref FROM device_capabilities WHERE vendor = 'CliCo'")).all()
        ev = c.execute(text("SELECT count(*) FROM events_outbox WHERE event_type = 'device.capabilities.changed' AND tenant_id = :t"),
                       {"t": seed["A"]}).scalar()
    assert sorted((r.certification, r.evidence_ref) for r in rows) == [("certified", "lab-cli-2"), ("identified", None)] and ev >= 3
