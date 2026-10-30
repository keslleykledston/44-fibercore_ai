"""Bench gate (ADR-0030, H0 cloud side): a write opens ONLY for the closed list of bench targets, through six fail-closed conditions
(global gate untouched), a single-use PRIOR authorization consumed with the approval, signed into the envelope, and a write lock after any
non-successful outcome."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api import jobs as jobs_mod
from app.core import bench, jobsign
from app.core.security import hash_secret
from tests.conftest import agent, hdr, login
from tests.test_jobs import _pub_b64, idem, login_as

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "job-envelope.schema.json").read_text())
SERIAL, EXT = "BNCH-CPE-0001", "bench-ext-0001"
PROFILE = ("Huawei Technologies Co., Ltd", "EG8145V5", "V5R019C10S350")


@pytest.fixture(autouse=True)
def _cleanup(migrated, monkeypatch):
    monkeypatch.setattr(bench, "EDGE_SUPPORT", True)  # the Edge side is a separate PR: tests that exercise the cloud gate assume it exists
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features"))
        c.execute(text("DELETE FROM bench_authorizations"))
        c.execute(text("DELETE FROM job_approvals WHERE job_id IN (SELECT id FROM jobs WHERE operation = 'reboot_cpe')"))
        c.execute(text("DELETE FROM jobs WHERE operation = 'reboot_cpe'"))
        c.execute(text("DELETE FROM bench_targets"))
        c.execute(text("DELETE FROM bench_target_epochs"))
        c.execute(text("DELETE FROM device_capabilities"))
        c.execute(text("DELETE FROM cpe_protocol_bindings WHERE cpe_id IN (SELECT id FROM cpes WHERE canonical_serial LIKE 'BNCH-%')"))
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'BNCH-%'"))


def _flag(migrated, tenant, on=True):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'bench_writes',:e)"), {"t": tenant, "e": on})


def _cpe(client, inv, seed, firmware=PROFILE[2], serial=SERIAL, ext=EXT):
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": datetime.now(UTC).isoformat(), "cpes": [
        {"canonical_serial": serial, "vendor": PROFILE[0], "model": PROFILE[1], "firmware": firmware,
         "binding": {"protocol": "tr069", "external_id": ext, "connector_id": "c-bench"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    return next(c["id"] for c in client.get("/v1/cpes", headers=hdr(client, "alice", seed, "A")).json() if c["canonical_serial"] == serial)


def _bench(migrated, seed, inv, cpe, **kw):
    """The full set of conditions; `kw` removes or changes ONE of them."""
    t = str(seed["A"])
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t})
        if kw.get("target", True):
            c.execute(text("INSERT INTO bench_targets (tenant_id, cpe_id, edge_id, owner_epoch) VALUES (:t,:c,:e,3)"),
                      {"t": t, "c": cpe, "e": str(inv["a1"]["edge"])})
        if kw.get("capability", True):
            c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, "
                           "verified_at, evidence_ref) VALUES (:t,:v,:m,:f,'tr069','reboot_cpe',:s,:cert,CAST(:va AS timestamptz),:ev)"),
                      {"t": t, "v": PROFILE[0], "m": PROFILE[1], "f": PROFILE[2], "s": kw.get("status", "supported"),
                       "cert": kw.get("cert", "observed"), "va": None if kw.get("no_evidence") else datetime.now(UTC).isoformat(),
                       "ev": None if kw.get("no_evidence") else "docs/wiki/bench/H2-reboot_cpe-test.md"})
        if kw.get("authorization", True) and kw.get("target", True):
            now = datetime.now(UTC)
            c.execute(text("INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by, first_run) "
                           "VALUES (:t,'reboot_cpe',:c,:h,:s,:e,'responsavel',:fr)"),
                      {"t": t, "c": cpe, "fr": kw.get("first_run", False), "h": kw.get("hash", bench.params_hash({})), "s": now + timedelta(seconds=kw.get("start", -60)),
                       "e": now + timedelta(seconds=kw.get("end", 1800))})


def _approver(client, seed, migrated):
    email = f"benchapprover-{uuid4().hex[:6]}@example.com"
    with migrated.begin() as c:
        uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,'Approver',:h) RETURNING id"),
                        {"e": email, "h": hash_secret("correct horse battery")}).scalar()
        c.execute(text("INSERT INTO tenant_memberships VALUES (:t,:u,'isp_admin')"), {"t": seed["A"], "u": uid})
    return {**login_as(client, email), "X-Workspace-ID": str(seed["A"])}


def _preview(client, h, cpe):
    return client.post("/v1/jobs/preview", headers={**h, **idem()}, json={"operation": "reboot_cpe", "target_id": cpe})


def _full(client, seed, inv, migrated, **kw):
    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, **kw)
    return cpe, hdr(client, "alice", seed, "A")


def test_flag_off_keeps_the_global_gate_even_with_every_other_condition(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe)  # target, registry and authorization exist; the tenant flag does not
    h = hdr(client, "alice", seed, "A")
    jid = _preview(client, h, cpe).json()["id"]
    r = client.post(f"/v1/jobs/{jid}/submit", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "operation_not_homologated"
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "PREVIEWED"


@pytest.mark.parametrize("kw,reason", [
    ({"target": False}, "target_not_bench"),
    ({"capability": False}, "capability_not_observed"),
    ({"status": "unknown"}, "capability_not_observed"),     # an `unknown` row is not a claim
    ({"cert": "identified"}, "capability_not_observed"),
    ({"authorization": False}, "authorization_missing"),
    ({"hash": "0" * 64}, "authorization_missing"),          # an authorization for other parameters
    ({"end": -10, "start": -600}, "authorization_missing"), # window already closed
    ({"start": 600, "end": 1200}, "authorization_missing"), # window not open yet
])
def test_each_condition_is_required_and_refuses_with_its_reason(client, seed, inv, migrated, kw, reason):
    cpe, h = _full(client, seed, inv, migrated, **kw)
    jid = _preview(client, h, cpe).json()["id"]
    r = client.post(f"/v1/jobs/{jid}/submit", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == reason, r.text
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204


def test_firmware_must_match_the_registry_exactly_and_missing_firmware_refuses(client, seed, inv, migrated):
    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed, firmware="V5R019C10S999")  # another firmware of the same model
    _bench(migrated, seed, inv, cpe)
    h = hdr(client, "alice", seed, "A")
    r = client.post(f"/v1/jobs/{_preview(client, h, cpe).json()['id']}/submit", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "capability_not_observed"
    with migrated.begin() as c:
        c.execute(text("UPDATE cpes SET firmware = NULL WHERE id = :c"), {"c": cpe})
    r = client.post(f"/v1/jobs/{_preview(client, h, cpe).json()['id']}/submit", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "capability_not_observed"


def test_global_gate_still_blocks_everything_that_is_not_a_bench_operation(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated)
    for op in ("set_wifi_ssid", "provision_onu"):
        target = cpe if op == "set_wifi_ssid" else None
        if target is None:
            continue
        jid = client.post("/v1/jobs/preview", headers={**h, **idem()}, json={"operation": op, "target_id": target}).json()["id"]
        r = client.post(f"/v1/jobs/{jid}/submit", headers=h)
        assert r.status_code == 409 and r.json()["detail"] == "operation_not_homologated", op  # not in the bench catalog (yet)
    assert jobs_mod.HOMOLOGATED_WRITES == frozenset()


def test_bench_reboot_full_path_authorization_is_consumed_with_the_approval_and_signed(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated)
    pv = _preview(client, h, cpe).json()
    assert pv["required_approvals"] == 1 and pv["risk"] == "R1"          # a bench write always needs one approval
    jid = pv["id"]
    assert client.post(f"/v1/jobs/{jid}/submit", headers=h).json()["status"] == "PENDING_APPROVAL"
    assert client.post(f"/v1/jobs/{jid}/approve", headers=h).status_code == 403  # the requester cannot approve
    with migrated.begin() as c:
        assert c.execute(text("SELECT state FROM bench_authorizations")).scalar() == "open"  # not consumed by a mere submit
    ap = _approver(client, seed, migrated)
    done = client.post(f"/v1/jobs/{jid}/approve", headers=ap)
    assert done.status_code == 200 and done.json()["status"] == "APPROVED", done.text
    with migrated.begin() as c:
        a = c.execute(text("SELECT id, state, job_id, window_end FROM bench_authorizations")).one()
        j = c.execute(text("SELECT authorization_id, owner_epoch FROM jobs WHERE id = :j"), {"j": jid}).one()
    assert a.state == "consumed" and str(a.job_id) == jid and j.authorization_id == a.id and j.owner_epoch == 3
    env = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    assert env.status_code == 200
    env = env.json()
    assert not list(Draft202012Validator(SCHEMA).iter_errors(env)) and jobsign.verify(_pub_b64(), env)
    assert env["operation"] == "reboot_cpe" and env["target_ref"] == EXT and env["owner_epoch"] == 3
    assert env["authorization_id"] == str(a.id) and env["authorization_ends_at"] == a.window_end.isoformat()
    assert datetime.fromisoformat(env["expires_at"]) <= a.window_end  # never valid beyond the authorization window
    issued = datetime.fromisoformat(env["issued_at"])
    assert datetime.fromisoformat(env["expires_at"]) - issued <= bench.ENVELOPE_TTL  # and short-lived on its own
    for field in ("authorization_id", "owner_epoch", "target_ref"):    # all covered by the signature
        assert not jobsign.verify(_pub_b64(), {**env, field: "tampered" if field != "owner_epoch" else 9})


def test_no_envelope_leaves_without_the_confirmed_transition_to_dispatched(client, seed, inv, migrated, monkeypatch):
    cpe, h = _full(client, seed, inv, migrated)
    jid = _preview(client, h, cpe).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    client.post(f"/v1/jobs/{jid}/approve", headers=_approver(client, seed, migrated))
    real = jobs_mod.cas
    monkeypatch.setattr(jobs_mod, "cas", lambda conn, job, to, **kw: False if to == "DISPATCHED" else real(conn, job, to, **kw))
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204  # signed, but never returned
    monkeypatch.setattr(jobs_mod, "cas", real)
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "APPROVED"


def test_an_authorization_is_single_use_and_a_refused_approval_commits_nothing(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated)
    ap = _approver(client, seed, migrated)
    first = _preview(client, h, cpe).json()["id"]
    client.post(f"/v1/jobs/{first}/submit", headers=h)
    second = _preview(client, h, cpe).json()["id"]
    client.post(f"/v1/jobs/{second}/submit", headers=h)  # both pass submit: the authorization is still open
    assert client.post(f"/v1/jobs/{first}/approve", headers=ap).json()["status"] == "APPROVED"
    r = client.post(f"/v1/jobs/{second}/approve", headers=ap)
    assert r.status_code == 409 and r.json()["detail"] == "authorization_missing"
    with migrated.begin() as c:
        n = c.execute(text("SELECT count(*) FROM job_approvals WHERE job_id = :j"), {"j": second}).scalar()
        st = c.execute(text("SELECT status FROM jobs WHERE id = :j"), {"j": second}).scalar()
    assert n == 0 and st == "PENDING_APPROVAL"  # the failed approval left no trace


def test_dispatch_rechecks_the_window_and_cancels_when_it_closed(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated)
    jid = _preview(client, h, cpe).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    assert client.post(f"/v1/jobs/{jid}/approve", headers=_approver(client, seed, migrated)).json()["status"] == "APPROVED"
    with migrated.begin() as c:  # the window closes before the Edge polls
        c.execute(text("UPDATE bench_authorizations SET window_start = now() - interval '2 hours', window_end = now() - interval '1 minute'"))
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "CANCELLED"


def _dispatched(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated)
    jid = _preview(client, h, cpe).json()["id"]
    client.post(f"/v1/jobs/{jid}/submit", headers=h)
    client.post(f"/v1/jobs/{jid}/approve", headers=_approver(client, seed, migrated))
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 200
    return cpe, h, jid


@pytest.mark.parametrize("report,locked", [({"state": "failed"}, True), ({"state": "succeeded", "postcheck_ok": False}, True),
                                            ({"state": "succeeded", "postcheck_ok": True}, False)])
def test_any_outcome_that_is_not_a_confirmed_success_locks_the_target(client, seed, inv, migrated, report, locked):
    cpe, h, jid = _dispatched(client, seed, inv, migrated)
    assert client.post(f"/v1/edge/jobs/{jid}/result", headers=agent(client, inv, "a1"), json=report).status_code == 204
    with migrated.begin() as c:
        assert c.execute(text("SELECT write_locked FROM bench_targets")).scalar() is locked
    if locked:  # no retry and no new write until the owner reconciles it
        _bench_again = _preview(client, h, cpe).json()["id"]
        r = client.post(f"/v1/jobs/{_bench_again}/submit", headers=h)
        assert r.status_code == 409 and r.json()["detail"] == "target_write_locked"


def test_a_dispatched_job_that_is_never_reported_locks_the_target(client, seed, inv, migrated):
    cpe, h, jid = _dispatched(client, seed, inv, migrated)
    with migrated.begin() as c:
        c.execute(text("UPDATE jobs SET expires_at = now() - interval '1 hour' WHERE id = :j"), {"j": jid})
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204  # the sweep runs here
    with migrated.begin() as c:
        assert c.execute(text("SELECT status FROM jobs WHERE id = :j"), {"j": jid}).scalar() == "EXPIRED"
        assert c.execute(text("SELECT write_locked, lock_reason FROM bench_targets")).one()[0] is True


def test_the_app_role_cannot_write_the_bench_lists_and_tenants_are_isolated(client, seed, inv, migrated):
    cpe, _ = _full(client, seed, inv, migrated)
    for stmt in ("INSERT INTO bench_targets (tenant_id, cpe_id, edge_id) VALUES (:t, :c, :e)",
                 "UPDATE bench_targets SET edge_id = :e", "DELETE FROM bench_targets",
                 "INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by) "
                 "VALUES (:t,'reboot_cpe',:c,repeat('a',64),now(),now() + interval '1 hour','x')",
                 "UPDATE bench_authorizations SET window_end = now() + interval '3 hours'", "DELETE FROM bench_authorizations"):
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text("SET LOCAL ROLE fibercore_app"))
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(stmt), {"t": str(seed["A"]), "c": cpe, "e": str(inv["a1"]["edge"])})
    with migrated.begin() as c:
        c.execute(text("SET LOCAL ROLE fibercore_app"))
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
        assert c.execute(text("SELECT (SELECT count(*) FROM bench_targets) + (SELECT count(*) FROM bench_authorizations)")).scalar() == 0


def test_authorization_window_is_bounded_and_ties_to_a_bench_target(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    now = datetime.now(UTC)
    for kw in ({"end": now + timedelta(hours=5)}, {"end": now}):  # longer than 4 h, or not after the start
        with pytest.raises(DBAPIError), migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text("INSERT INTO bench_targets (tenant_id, cpe_id, edge_id) VALUES (:t,:c,:e)"),
                      {"t": str(seed["A"]), "c": cpe, "e": str(inv["a1"]["edge"])})
            c.execute(text("INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by) "
                           "VALUES (:t,'reboot_cpe',:c,repeat('a',64),:s,:e,'x')"), {"t": str(seed["A"]), "c": cpe, "s": now, "e": kw["end"]})
    with pytest.raises(DBAPIError), migrated.begin() as c:  # an authorization for a CPE that is not a bench target
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by) "
                       "VALUES (:t,'reboot_cpe',:c,repeat('a',64),now(),now() + interval '1 hour','x')"), {"t": str(seed["A"]), "c": cpe})


def test_bench_evidence_file_check_and_the_catalog():
    ok = "\n".join(f"- **{f}:** valor" for f in bench.EVIDENCE_FIELDS)
    assert bench.evidence_missing(ok) == []
    assert bench.evidence_missing(ok.replace("- **Estado depois:** valor", "- **Estado depois:**")) == ["Estado depois"]  # empty field
    assert "Aprovador" in bench.evidence_missing("\n".join(ok.splitlines()[:-4]))
    assert bench.evidence_missing(ok + "\n- **Nota:** 192.168.0.1")[-1].startswith("conteúdo sensível")
    assert bench.evidence_missing(ok + "\nsenha: x")[-1].startswith("conteúdo sensível")
    assert set(bench.BENCH_OPS) == {"reboot_cpe"} and bench.MIN_APPROVALS == 1
    assert all(jobs_mod.OPERATIONS[o].writes for o in bench.BENCH_OPS)  # the catalog is a subset of the engine's write operations


def test_login_helper_is_unused_but_alice_is_the_requester(client, seed):
    assert login(client, "alice")  # sanity: the requester of every test here is a real tenant-A admin


def test_owner_cli_manages_targets_authorizations_locks_and_checks_the_evidence(client, seed, inv, migrated, admin_url, monkeypatch, tmp_path):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t, edge = str(seed["A"]), str(inv["a1"]["edge"])
    cpe = _cpe(client, inv, seed)
    now = datetime.now(UTC)
    iso = lambda m: (now + timedelta(minutes=m)).isoformat()  # noqa: E731
    with pytest.raises(SystemExit, match="owned by another edge"):  # the target's Edge is the CPE's owner Edge, no other pairing
        cli.main(["bench-target-add", t, cpe, str(inv["a2"]["edge"])])
    with pytest.raises(SystemExit, match="owned by another edge"):
        cli.main(["bench-target-add", t, str(uuid4()), edge])
    cli.main(["bench-target-add", t, cpe, edge, "--note", "bancada"])
    with pytest.raises(SystemExit, match="not in the bench catalog"):
        cli.main(["bench-authorize", t, "set_wifi_ssid", cpe, "--from", iso(-1), "--to", iso(30), "--by", "responsavel"])
    with pytest.raises(SystemExit, match="time zone"):
        cli.main(["bench-authorize", t, "reboot_cpe", cpe, "--from", "2026-10-30T10:00:00", "--to", "2026-10-30T11:00:00", "--by", "r"])
    with pytest.raises(DBAPIError):  # more than 4 hours
        cli.main(["bench-authorize", t, "reboot_cpe", cpe, "--from", iso(-1), "--to", iso(300), "--by", "responsavel"])
    cli.main(["bench-authorize", t, "reboot_cpe", cpe, "--from", iso(-1), "--to", iso(30), "--by", "responsavel"])
    with pytest.raises(SystemExit, match="refused"):  # an open authorization keeps the target in the list
        cli.main(["bench-target-remove", t, cpe])
    with pytest.raises(SystemExit, match="not locked"):
        cli.main(["bench-unlock", t, cpe, "--reason", "nothing to do"])
    with migrated.begin() as c:
        c.execute(text("UPDATE bench_targets SET write_locked = true, lock_reason = 'test'"))
    cli.main(["bench-unlock", t, cpe, "--reason", "reconciled by hand after the bench run"])
    with migrated.begin() as c:
        assert c.execute(text("SELECT write_locked FROM bench_targets")).scalar() is False
        c.execute(text("UPDATE bench_authorizations SET window_end = now() - interval '1 minute', window_start = now() - interval '2 hours'"))
    cli.main(["bench-target-remove", t, cpe])
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM bench_targets")).scalar() == 0
    cli.main(["bench-target-add", t, cpe, edge])  # added again: the generation moved forward, it did not restart
    with migrated.begin() as c:
        assert c.execute(text("SELECT owner_epoch FROM bench_targets")).scalar() == 2
    # capability evidence: a bench operation needs the checked file; `certified` is never granted by ADR-0030
    base = [t, *PROFILE, "tr069", "reboot_cpe", "supported"]
    claim = ["--evidence", "docs/wiki/bench/H2-reboot_cpe-test.md", "--verified-at", now.isoformat()]
    with pytest.raises(SystemExit, match="needs --evidence-file"):
        cli.main(["capability-set", *base, "observed", *claim])
    good = tmp_path / "ok.md"
    good.write_text("\n".join(f"- **{f}:** valor" for f in bench.EVIDENCE_FIELDS), encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("- **Hash da intenção:** x\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="incomplete"):
        cli.main(["capability-set", *base, "observed", *claim, "--evidence-file", str(bad)])
    with pytest.raises(SystemExit, match="cannot read"):
        cli.main(["capability-set", *base, "observed", *claim, "--evidence-file", str(tmp_path / "absent.md")])
    with pytest.raises(SystemExit, match="not granted by ADR-0030"):
        cli.main(["capability-set", *base, "certified", *claim, "--evidence-file", str(good)])
    cli.main(["capability-set", *base, "observed", *claim, "--evidence-file", str(good)])
    with migrated.begin() as c:
        assert c.execute(text("SELECT certification FROM device_capabilities WHERE operation = 'reboot_cpe'")).scalar() == "observed"


def test_nothing_can_be_enabled_or_dispatched_while_the_edge_support_is_missing(client, seed, inv, migrated, admin_url, monkeypatch):
    from app import cli

    cpe, h = _full(client, seed, inv, migrated)  # flag, target, registry and authorization are all in place (written directly)
    jid = _preview(client, h, cpe).json()["id"]
    monkeypatch.setattr(bench, "EDGE_SUPPORT", False)
    r = client.post(f"/v1/jobs/{jid}/submit", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "operation_not_homologated"  # the bench path is invisible
    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    with pytest.raises(SystemExit, match="cannot be turned on"):
        cli.main(["feature-set", str(seed["A"]), "bench_writes", "on"])
    with pytest.raises(SystemExit, match="no bench authorization can be recorded"):
        cli.main(["bench-authorize", str(seed["A"]), "reboot_cpe", cpe, "--from", datetime.now(UTC).isoformat(),
                  "--to", (datetime.now(UTC) + timedelta(minutes=5)).isoformat(), "--by", "r"])
    cli.main(["feature-set", str(seed["A"]), "bench_writes", "off"])  # turning it OFF is always allowed
    assert bench.EDGE_SUPPORT is False


def test_the_shipped_default_has_the_edge_support_but_every_other_condition_stays_closed(client, seed, inv):
    import importlib

    assert importlib.reload(bench).EDGE_SUPPORT is True   # flipped by the PR that implements and tests the Edge side
    assert bench.BENCH_OPS.keys() == {"reboot_cpe"}       # still one operation; H3/H4 need an ADR amendment
    assert features_default("bench_writes") is False      # the tenant flag still defaults off


# ---- bench lease (ADR-0030 item 4): renewed on every poll, withdrawn as soon as the target stops being eligible --------------------------
def _lease(resp):
    import base64
    h = resp.headers.get("X-Bench-Lease")
    return None if h is None else json.loads(base64.b64decode(h))


def test_the_lease_rides_every_poll_answer_is_signed_and_short_lived(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated)
    r = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    assert r.status_code == 204                                                # no job, and still a lease
    lease = _lease(r)
    assert lease["schema"] == "bench-lease/1" and lease["edge_id"] == str(inv["a1"]["edge"]) and lease["tenant_id"] == str(seed["A"])
    assert lease["targets"] == [{"target_ref": EXT, "owner_epoch": 3}]
    assert jobsign.verify(_pub_b64(), lease)
    assert datetime.fromisoformat(lease["expires_at"]) - datetime.fromisoformat(lease["issued_at"]) <= bench.LEASE_TTL
    assert not jobsign.verify(_pub_b64(), {**lease, "targets": [{"target_ref": "other-device", "owner_epoch": 3}]})
    # a poll of ANOTHER edge never carries this edge's targets
    other = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "b1"))
    assert _lease(other) is None


@pytest.mark.parametrize("withdraw", ["locked", "flag", "removed", "edge_support"])
def test_the_lease_is_withdrawn_when_the_target_stops_being_eligible(client, seed, inv, migrated, monkeypatch, withdraw):
    cpe, h = _full(client, seed, inv, migrated)
    assert _lease(client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))) is not None
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        if withdraw == "locked":
            c.execute(text("UPDATE bench_targets SET write_locked = true, lock_reason = 'test'"))
        elif withdraw == "flag":
            c.execute(text("UPDATE tenant_features SET enabled = false WHERE feature = 'bench_writes'"))
        elif withdraw == "removed":
            c.execute(text("DELETE FROM bench_authorizations"))   # the owner CLI refuses to remove a target with an open authorization
            c.execute(text("DELETE FROM bench_targets"))
    if withdraw == "edge_support":
        monkeypatch.setattr(bench, "EDGE_SUPPORT", False)
    assert _lease(client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))) is None


def test_no_lease_without_a_bench_target_and_none_by_default(client, seed, inv, migrated, monkeypatch):
    assert _lease(client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))) is None
    monkeypatch.setattr(bench, "EDGE_SUPPORT", False)
    _full(client, seed, inv, migrated)
    assert _lease(client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))) is None


GOLDEN_LEASE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "edge" / "bench_lease_signed.golden.json"
GOLDEN_SEED = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="  # a public TEST seed (32 bytes of 0x01): signs only this fixture


def test_golden_lease_matches_what_the_edge_verifies():
    import base64

    from cryptography.hazmat.primitives import serialization
    key = jobsign.load_private(GOLDEN_SEED)
    body = {"schema": "bench-lease/1", "tenant_id": "22222222-2222-4222-8222-222222222222", "edge_id": "33333333-3333-4333-8333-333333333333",
            "issued_at": "2026-10-30T12:00:00+00:00", "expires_at": "2026-10-30T12:02:00+00:00",
            "targets": [{"target_ref": "00259E-EG8145V5-48575443E2247AA5", "owner_epoch": 2}]}
    body["signature"] = jobsign.sign(key, body)
    pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    golden = {"public_key_b64": pub, "header": base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()}
    assert GOLDEN_LEASE.exists(), "generate with: regenerate the fixture from this test body (public test seed)"
    assert json.loads(GOLDEN_LEASE.read_text()) == golden


def features_default(name):
    from app.core import features
    return features.FEATURES[name]


# ---- first run (ADR-0030 amendment): the owner's prior authorization stands in for the `observed` entry that only the evidence can create ----
def _run_to_dispatch(client, seed, inv, migrated, h, cpe):
    jid = _preview(client, h, cpe).json()["id"]
    r = client.post(f"/v1/jobs/{jid}/submit", headers=h)
    if r.status_code != 200 and r.status_code != 202:
        return jid, r
    return jid, client.post(f"/v1/jobs/{jid}/approve", headers=_approver(client, seed, migrated))


def test_first_run_authorization_opens_the_gate_with_an_identified_entry_and_stays_single_use(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated, cert="identified", first_run=True)
    jid, r = _run_to_dispatch(client, seed, inv, migrated, h, cpe)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED", r.text
    env = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    assert env.status_code == 200 and env.json()["operation"] == "reboot_cpe"
    with migrated.begin() as c:
        assert c.execute(text("SELECT state FROM bench_authorizations")).scalar() == "consumed"
    # the same authorization cannot open a second job, and no new one exists
    jid2 = _preview(client, h, cpe).json()["id"]
    r2 = client.post(f"/v1/jobs/{jid2}/submit", headers=h)
    assert r2.status_code == 409 and r2.json()["detail"] == "capability_not_observed"


@pytest.mark.parametrize("kw", [
    {"cert": "identified", "first_run": False},                      # identified alone never opens a write
    {"capability": False, "first_run": True},                         # first_run does not replace the registry entry altogether
    {"cert": "identified", "first_run": True, "status": "unknown"},   # an `unknown` row is not a claim
])
def test_first_run_needs_a_complete_identified_supported_entry(client, seed, inv, migrated, kw):
    cpe, h = _full(client, seed, inv, migrated, **kw)
    jid = _preview(client, h, cpe).json()["id"]
    r = client.post(f"/v1/jobs/{jid}/submit", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "capability_not_observed", r.text


def test_the_registry_itself_refuses_a_supported_entry_without_evidence(client, seed, inv, migrated):
    cpe = _cpe(client, inv, seed)
    with pytest.raises(DBAPIError):   # the `identified` entry that a first run relies on is always complete: the database enforces it
        _bench(migrated, seed, inv, cpe, cert="identified", first_run=True, no_evidence=True)


def test_first_run_is_rechecked_at_dispatch_when_the_registry_changes(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated, cert="identified", first_run=True)
    jid, r = _run_to_dispatch(client, seed, inv, migrated, h, cpe)
    assert r.json()["status"] == "APPROVED"
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM device_capabilities"))
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204
    assert client.get(f"/v1/jobs/{jid}", headers=h).json()["status"] == "CANCELLED"


def test_a_normal_authorization_works_once_observed_exists_and_first_run_is_then_moot(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated, first_run=True)  # `observed` entry present
    jid, r = _run_to_dispatch(client, seed, inv, migrated, h, cpe)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED", r.text


def test_owner_cli_records_the_first_run_flag(client, seed, inv, migrated, admin_url, monkeypatch):
    from app import cli

    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, authorization=False, cert="identified")
    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    now = datetime.now(UTC)
    cli.main(["bench-authorize", str(seed["A"]), "reboot_cpe", cpe, "--from", now.isoformat(), "--to", (now + timedelta(minutes=5)).isoformat(),
              "--by", "responsavel", "--first-run"])
    with migrated.begin() as c:
        assert c.execute(text("SELECT first_run FROM bench_authorizations")).scalar() is True


def test_first_run_cli_refuses_without_identified_entry_with_observed_entry_and_a_second_open_one(client, seed, inv, migrated, admin_url, monkeypatch):
    from app import cli

    _flag(migrated, seed["A"])
    cpe = _cpe(client, inv, seed)
    _bench(migrated, seed, inv, cpe, authorization=False, capability=False)
    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    now = datetime.now(UTC)
    argv = ["bench-authorize", str(seed["A"]), "reboot_cpe", cpe, "--from", now.isoformat(), "--to", (now + timedelta(minutes=5)).isoformat(),
            "--by", "responsavel", "--first-run"]
    with pytest.raises(SystemExit, match="needs a complete"):
        cli.main(argv)                                         # no registry entry at all
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, "
                       "verified_at, evidence_ref) VALUES (:t,:v,:m,:f,'tr069','reboot_cpe','supported','identified',now(),'docs/x.md')"),
                  {"t": str(seed["A"]), "v": PROFILE[0], "m": PROFILE[1], "f": PROFILE[2]})
    cli.main(argv)                                             # one open first-run authorization
    with pytest.raises(Exception, match="one_open_first_run|duplicate key"):
        cli.main(argv)                                         # the owner cannot stack a second one
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE device_capabilities SET certification = 'observed'"))
        c.execute(text("DELETE FROM bench_authorizations"))
    with pytest.raises(SystemExit, match="observed entry already exists"):
        cli.main(argv)                                         # moot once the evidence-backed entry exists


def test_the_gate_scopes_every_lookup_to_the_tenant_it_is_given(client, seed, inv, migrated):
    cpe, h = _full(client, seed, inv, migrated, cert="identified", first_run=True)
    jid = _preview(client, h, cpe).json()["id"]
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        job = c.execute(text("SELECT id, operation, target_id, target_type, edge_id, params FROM jobs WHERE id = :j"), {"j": jid}).one()
        assert bench.gate(c, seed["A"], job, mode="submit") is None
        # the same rows, visible through the session (RLS is set to A), are NOT usable under another tenant id: every lookup names the tenant
        for mode in ("submit", "consume", "dispatch"):
            assert bench.gate(c, seed["B"], job, mode=mode) in ("bench_writes_disabled", "target_not_bench")
