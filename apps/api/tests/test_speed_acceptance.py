"""ADR-0038 amendment (2026-10-31), option C: the formal acceptance of the 3xx risk on the bench. The decision is a database row written only by the
owner CLI; the gate reads it for THIS destination, at this moment, under the lock the registry promotion uses."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import bench, speed
from tests.conftest import agent, hdr
from tests.test_jobs_bench import PROFILE, _approver
from tests.test_jobs_bench import _cleanup as _bench_cleanup  # noqa: F401  (autouse: bench lists, authorizations, registry, CPEs)
from tests.test_speed import (
    EP,
    _link,
    _post,
    _ready,
    _rows,
    _speed_cleanup,  # noqa: F401  (autouse: runs, endpoints, jobs)
)


@pytest.fixture(autouse=True)
def _acceptance_cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM speed_risk_acceptances"))


def _probe_follows(migrated, seed):
    """The real finding: the client FOLLOWS a 3xx (probe row `unsupported`, observed, with evidence). _ready() wrote `supported`; flip it."""
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE device_capabilities SET status = 'unsupported' WHERE operation = :o"), {"o": speed.REDIRECT_PROBE})


def _accept(migrated, seed, *, endpoints=(EP,), firmware=PROFILE[2], accepted=None, expires=None, revoked=False, vendor=PROFILE[0], model=PROFILE[1]):
    today = datetime.now(UTC).date()
    accepted = accepted or today
    expires = expires or (accepted + timedelta(days=30))
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        return c.execute(text(
            "INSERT INTO speed_risk_acceptances (tenant_id, vendor, model, firmware, endpoint_ids, approved_by, accepted_on, expires_on, doc_ref, doc_sha256, revoked_at) "
            "VALUES (:t,:v,:m,:f,:e,'Responsável',:a,:x,'docs/wiki/bench/ACEITE-risco-3xx-teste-2026-10-31.md',:h, CASE WHEN :r THEN now() END) RETURNING id"),
            {"t": seed["A"], "v": vendor, "m": model, "f": firmware, "e": list(endpoints), "a": accepted, "x": expires, "h": "a" * 64, "r": revoked}).scalar()


def _basis(migrated, seed, target=EP, firmware=PROFILE[2]):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        return speed.redirect_basis(c, seed["A"], PROFILE[0], PROFILE[1], firmware, target)


def _setup(client, seed, inv, migrated, **accept_kw):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    _probe_follows(migrated, seed)
    if accept_kw is not None:
        _accept(migrated, seed, **accept_kw)
    return cpe, hdr(client, "alice", seed, "A")


# ---- the decision ---------------------------------------------------------------------------------------------------------------------------------
def test_a_client_that_follows_3xx_without_an_acceptance_stays_unverified(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    _probe_follows(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    assert _basis(migrated, seed) is None
    r = _post(client, h, cpe)
    assert r.status_code == 409 and r.json()["reason"] == "redirect_unverified"


def test_a_valid_acceptance_opens_exactly_that_destination_for_exactly_that_firmware(client, seed, inv, migrated):
    cpe, h = _setup(client, seed, inv, migrated)
    assert _basis(migrated, seed) == "acceptance"
    assert _basis(migrated, seed, target=None) == "acceptance"      # the capability listing, before a destination is chosen
    assert _basis(migrated, seed, target="core-other") is None       # a destination the acceptance does not name
    assert _basis(migrated, seed, firmware="V5R999") is None         # another firmware: the acceptance does not follow it
    assert client.get(f"/v1/cpes/{cpe}/speed/capabilities", headers=h).json()["directions"]["download"]["offered"] is True
    r = _post(client, h, cpe)
    assert r.status_code == 201, r.text


def test_the_other_bases_still_win_and_the_probe_is_required_to_know_the_risk(client, seed, inv, migrated):
    cpe, h = _setup(client, seed, inv, migrated)
    with migrated.begin() as c:   # no probe row at all: the risk is not known, an acceptance alone is not enough
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM device_capabilities WHERE operation = :o"), {"o": speed.REDIRECT_PROBE})
    assert _basis(migrated, seed) is None
    with migrated.begin() as c:   # the probe says the client does NOT follow: that is the stronger basis
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, verified_at, evidence_ref) "
                       "VALUES (:t,:v,:m,:f,'tr069',:o,'supported','observed',now(),'docs/x.md')"),
                  {"t": seed["A"], "v": PROFILE[0], "m": PROFILE[1], "f": PROFILE[2], "o": speed.REDIRECT_PROBE})
    assert _basis(migrated, seed) == "probe"


def test_an_internet_destination_is_never_accepted(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    _probe_follows(migrated, seed)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE speed_endpoints SET target_kind = 'INTERNET' WHERE id = :i"), {"i": EP})
    _accept(migrated, seed)   # the row names it, but it is not ours
    assert _basis(migrated, seed) is None
    assert _post(client, hdr(client, "alice", seed, "A"), cpe).json()["reason"] == "redirect_unverified"


@pytest.mark.parametrize("delta,live", [(0, True), (-1, False)])
def test_the_acceptance_is_valid_through_its_last_day_and_not_after(client, seed, inv, migrated, delta, live):
    _ready(client, seed, inv, migrated)
    _probe_follows(migrated, seed)
    today = datetime.now(UTC).date()
    _accept(migrated, seed, accepted=today - timedelta(days=10), expires=today + timedelta(days=delta))
    assert (_basis(migrated, seed) == "acceptance") is live


def test_the_database_refuses_more_than_ninety_days_and_a_blank_approver(migrated, seed):
    today = datetime.now(UTC).date()
    assert _accept(migrated, seed, accepted=today, expires=today + timedelta(days=89))
    assert _accept(migrated, seed, accepted=today, expires=today + timedelta(days=90))
    for kw in ({"expires": today + timedelta(days=91)}, {"expires": today}):
        with pytest.raises(DBAPIError):
            _accept(migrated, seed, accepted=today, **kw)
    with pytest.raises(DBAPIError), migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO speed_risk_acceptances (tenant_id, vendor, model, firmware, endpoint_ids, approved_by, accepted_on, expires_on, doc_ref, doc_sha256) "
                       "VALUES (:t,'v','m','f',ARRAY['x-node-1'],'  ',:a,:x,'docs/wiki/bench/ACEITE-risco-3xx-m-2026-10-31.md',:h)"),
                  {"t": seed["A"], "a": today, "x": today + timedelta(days=1), "h": "a" * 64})


def test_the_application_role_can_read_but_never_write_the_acceptances(client, seed, inv, migrated):
    _accept(migrated, seed)
    from app.core.db import get_engine
    with get_engine().begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        assert c.execute(text("SELECT count(*) FROM speed_risk_acceptances")).scalar() == 1
    for sql in ("UPDATE speed_risk_acceptances SET revoked_at = NULL", "DELETE FROM speed_risk_acceptances",
                "INSERT INTO speed_risk_acceptances (tenant_id, vendor, model, firmware, endpoint_ids, approved_by, accepted_on, expires_on, doc_ref, doc_sha256) "
                "VALUES (:t,'v','m','f',ARRAY['x-node-1'],'a',current_date,current_date+1,'docs/wiki/bench/ACEITE-risco-3xx-m-2026-10-31.md',repeat('a',64))"):
        with pytest.raises(DBAPIError), get_engine().begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
            c.execute(text(sql), {"t": seed["A"]})


def test_another_tenant_cannot_see_or_use_the_acceptance(client, seed, inv, migrated):
    _accept(migrated, seed)
    from app.core.db import get_engine as ge
    with ge().begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["B"])})
        assert c.execute(text("SELECT count(*) FROM speed_risk_acceptances")).scalar() == 0


# ---- revocation: at the request, at the approval and at the dispatch ------------------------------------------------------------------------------
def _revoke(migrated, seed, aid):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE speed_risk_acceptances SET revoked_at = now() WHERE id = :i"), {"i": aid})


def test_a_revoked_acceptance_stops_the_request_the_approval_and_the_dispatch(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    _probe_follows(migrated, seed)
    aid = _accept(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    run = _post(client, h, cpe).json()["run"]
    _revoke(migrated, seed, aid)                                   # revoked AFTER the request, BEFORE the approval
    r = client.post(f"/v1/jobs/{run['job_id']}/approve", headers=_approver(client, seed, migrated))
    assert r.status_code >= 400 or r.json().get("status") != "APPROVED"
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204
    assert _rows(migrated, "SELECT status FROM jobs WHERE id = :j", j=run["job_id"])[0].status in ("CANCELLED", "REJECTED", "PENDING_APPROVAL")


def test_revoked_after_the_approval_the_dispatch_refuses_and_cancels(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    _probe_follows(migrated, seed)
    aid = _accept(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    run = _post(client, h, cpe).json()["run"]
    assert client.post(f"/v1/jobs/{run['job_id']}/approve", headers=_approver(client, seed, migrated)).json()["status"] == "APPROVED"
    _revoke(migrated, seed, aid)                                   # revoked AFTER the approval, BEFORE the dispatch
    assert client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1")).status_code == 204
    assert _rows(migrated, "SELECT status FROM jobs WHERE id = :j", j=run["job_id"])[0].status == "CANCELLED"


def test_an_envelope_under_an_acceptance_lives_at_most_nine_minutes_fifteen_seconds(client, seed, inv, migrated):
    cpe = _ready(client, seed, inv, migrated)
    _link(migrated, seed, inv, cpe)
    _probe_follows(migrated, seed)
    _accept(migrated, seed)
    h = hdr(client, "alice", seed, "A")
    run = _post(client, h, cpe).json()["run"]
    assert client.post(f"/v1/jobs/{run['job_id']}/approve", headers=_approver(client, seed, migrated)).json()["status"] == "APPROVED"
    env = client.get("/v1/edge/jobs/next", headers=agent(client, inv, "a1"))
    assert env.status_code == 200
    e = env.json()
    life = datetime.fromisoformat(e["expires_at"]) - datetime.fromisoformat(e["issued_at"])
    # 10 min of worst-case exposure minus the 45 s of clock skew already tolerated between the Edge and the cloud
    assert life <= timedelta(minutes=9, seconds=15)
    assert life <= bench.ENVELOPE_TTL


# ---- serialization: a revocation and an envelope emission cannot interleave -----------------------------------------------------------------------
def test_the_gate_and_the_revocation_exclude_each_other_through_the_same_lock(client, seed, inv, migrated):
    key = bench.capability_lock_key(seed["A"], "speed_test_download")
    with migrated.connect() as gate_side, migrated.connect() as revoke_side:
        g = gate_side.begin()
        gate_side.execute(text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key})   # what bench.gate takes
        # the revocation (exclusive, as the owner CLI takes it) cannot be taken while an envelope is being emitted
        assert revoke_side.execute(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key}).scalar() is False
        revoke_side.rollback()
        g.commit()
        r = revoke_side.begin()
        assert revoke_side.execute(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key}).scalar() is True
        # and while the revocation is in progress a gate evaluation waits (here: cannot take the shared lock)
        assert gate_side.execute(text("SELECT pg_try_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key}).scalar() is False
        gate_side.rollback()
        r.rollback()


def test_the_gate_takes_that_lock_before_it_reads_the_acceptance(client, seed, inv, migrated):
    import inspect
    src = inspect.getsource(bench.gate)
    assert src.index("pg_advisory_xact_lock_shared") < src.index("speed.redirect_verified")


# ---- the owner CLI and the document ---------------------------------------------------------------------------------------------------------------
DOC = ("# Aceite do risco de redirecionamento 3xx\n\nFabricante: {v}\nModelo: {m}\nFirmware: {f}\nDestinos: {e}\nData: {d}\n\n"
       "Aprovado por: Fulano de Tal\n\nRisco residual: se o nó emitisse um 3xx a ONT seguiria o redirecionamento.\n")


def _doc(tmp_path, name="ACEITE-risco-3xx-eg8145v5-2026-10-31.md", **kw):
    f = {"v": PROFILE[0], "m": PROFILE[1], "f": PROFILE[2], "e": EP, "d": "2026-10-31"}
    f.update(kw)
    p = tmp_path / name
    p.write_text(DOC.format(**f))
    return p


def _gaps(p, **kw):
    a = {"vendor": PROFILE[0], "model": PROFILE[1], "firmware": PROFILE[2], "approved_by": "Fulano de Tal", "accepted_on": "2026-10-31", "endpoint_ids": [EP]}
    a.update(kw)
    return speed.acceptance_doc_gaps(p.name, p.read_text(), **a)


def test_the_document_check_names_every_gap(tmp_path):
    assert _gaps(_doc(tmp_path)) == []
    assert any("file name" in g for g in _gaps(_doc(tmp_path, name="aceite.md")))
    assert any("firmware" in g for g in _gaps(_doc(tmp_path), firmware="V5R000"))
    assert any("Aprovado por" in g for g in _gaps(_doc(tmp_path), approved_by="Outra Pessoa"))
    assert any("approved-by is empty" in g for g in _gaps(_doc(tmp_path), approved_by="  "))
    assert any("date" in g for g in _gaps(_doc(tmp_path), accepted_on="2026-11-02"))
    assert any("core-other" in g for g in _gaps(_doc(tmp_path), endpoint_ids=[EP, "core-other"]))
    p = _doc(tmp_path)
    p.write_text(p.read_text().replace("Risco residual", "Nota"))
    assert any("residual" in g for g in _gaps(p))
    p.write_text(p.read_text().replace("Aprovado por: Fulano de Tal", "Aprovado por:"))
    assert any("Aprovado por" in g for g in _gaps(p))


def test_the_owner_cli_records_audits_and_revokes_an_acceptance(client, seed, inv, migrated, admin_url, monkeypatch, tmp_path, capsys):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(seed["A"])
    _ready(client, seed, inv, migrated)
    doc = _doc(tmp_path, d=datetime.now(UTC).date().isoformat())
    today = datetime.now(UTC).date()
    args = ["speed-acceptance-set", t, PROFILE[0], PROFILE[1], PROFILE[2], "--endpoints", EP, "--approved-by", "Fulano de Tal",
            "--accepted-on", today.isoformat(), "--expires-on", (today + timedelta(days=30)).isoformat(), "--doc", str(doc)]
    with pytest.raises(SystemExit, match="3xx probe must be recorded first"):   # _ready() wrote `supported`: the probe does not say the client follows
        cli.main(args)
    _probe_follows(migrated, seed)
    for bad, msg in ((["--expires-on", (today + timedelta(days=91)).isoformat()], "at most 90 days"), (["--endpoints", "10.0.0.1"], "logical ids")):
        a = list(args)
        for i in range(0, len(bad), 2):
            a[a.index(bad[i]) + 1] = bad[i + 1]
        with pytest.raises(SystemExit, match=msg):
            cli.main(a)
    a = list(args)
    a[a.index("--accepted-on") + 1] = (today - timedelta(days=1)).isoformat()
    a[a.index("--expires-on") + 1] = (today + timedelta(days=30)).isoformat()
    with pytest.raises(SystemExit, match="incomplete"):   # the document states another date than the one given
        cli.main(a)
    a[a.index("--accepted-on") + 1] = (today + timedelta(days=1)).isoformat()
    a[a.index("--expires-on") + 1] = (today + timedelta(days=31)).isoformat()
    with pytest.raises(SystemExit, match="cannot be in the future"):   # a future date would only have its first day ignored by the gate; refuse it outright
        cli.main(a)
    cli.main(args)
    out = capsys.readouterr().out
    aid = _rows(migrated, "SELECT id, doc_sha256, doc_ref FROM speed_risk_acceptances")[0]
    assert aid.doc_sha256 == hashlib.sha256(doc.read_bytes()).hexdigest() and aid.doc_ref == "docs/wiki/bench/" + doc.name and "speed risk acceptance" in out
    assert _basis(migrated, seed) == "acceptance"
    # the audit: OK while the file is what was accepted; MISMATCH / MISSING once it changes or goes away (it does not change the gate: the row decides)
    with pytest.raises(SystemExit) as ok:
        cli.main(["speed-acceptance-audit", t, "--docs-dir", str(tmp_path)])
    assert ok.value.code == 0
    doc.write_text(doc.read_text() + "\nlinha a mais\n")
    with pytest.raises(SystemExit) as bad:
        cli.main(["speed-acceptance-audit", t, "--docs-dir", str(tmp_path)])
    assert bad.value.code == 1 and "MISMATCH" in capsys.readouterr().out
    assert _basis(migrated, seed) == "acceptance"        # the file changing does not move the gate
    doc.unlink()
    with pytest.raises(SystemExit) as gone:
        cli.main(["speed-acceptance-audit", t, "--docs-dir", str(tmp_path)])
    assert gone.value.code == 1 and "MISSING" in capsys.readouterr().out
    cli.main(["speed-acceptance-revoke", t, str(aid.id)])
    assert _basis(migrated, seed) is None
    with pytest.raises(SystemExit, match="no active acceptance"):
        cli.main(["speed-acceptance-revoke", t, str(aid.id)])


def test_an_acceptance_dated_in_the_future_is_not_in_force_yet(client, seed, inv, migrated):
    _ready(client, seed, inv, migrated)
    _probe_follows(migrated, seed)
    today = datetime.now(UTC).date()
    _accept(migrated, seed, accepted=today + timedelta(days=1), expires=today + timedelta(days=30))
    assert _basis(migrated, seed) is None
