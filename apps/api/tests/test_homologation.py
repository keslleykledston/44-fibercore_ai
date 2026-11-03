"""Homologation ledger (ADR-0041, PR6): the level is computed from evidence, a synthetic fixture counts for nothing, nobody is above L2 without a recorded certification."""
import copy
import hashlib
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core import homologation as hom
from tests.conftest import hdr

ROOT = Path(__file__).resolve().parents[3]


def _led():
    import json
    return json.loads(hom.DATA.read_text(encoding="utf-8"))


def _dev(led, model):
    return next(d for d in led["devices"] if d["model"] == model)


def test_the_shipped_ledger_is_valid_and_only_the_real_huawei_capture_reaches_l1():
    by = {d["model"]: d for d in hom.load()["items"]}
    assert by["MA5608T"]["level"] == "L1" and by["MA5800"]["level"] == "L0" and by["C300"]["level"] == "L0"   # synthetic fixtures never lift a level
    assert any("PON sem ONU" in b for b in by["MA5608T"]["next_blockers"]) and any("identified" in b for b in by["MA5608T"]["next_blockers"])
    assert all(len(d["coverage"]) == 22 for d in by.values()) and by["MA5608T"]["coverage"][10]["kind"] == "not_covered"   # test 11 (empty PON) is the known gap


def test_levels_are_computed_not_typed():
    led = _led()
    d = _dev(led, "MA5608T")
    assert hom.level_of(d)["level"] == "L1"
    obs = copy.deepcopy(d)
    obs["driver_level"] = "observed"
    assert hom.level_of(obs)["level"] == "L1"                                              # observed driver but no empty-PON evidence: still L1
    obs["coverage"]["11"] = {"kind": "real_fixture", "ref": "x/y.txt", "sha256": "0" * 64}
    assert hom.level_of(obs)["level"] == "L2"
    obs["coverage"]["11"]["kind"] = "synthetic_fixture"
    assert hom.level_of(obs)["level"] == "L1"                                              # a synthetic case does not count
    obs["coverage"]["11"] = {"kind": "unit_test", "ref": "a/b_test.go::TestX"}
    assert hom.level_of(obs)["level"] == "L1"                                              # a unit test proves our code, not the equipment: it cannot stand in for a real capture
    unit_only = copy.deepcopy(obs)
    unit_only["coverage"] = {k: {"kind": "unit_test", "ref": "a/b_test.go::TestX"} for k in ("3", "4", "6", "11", "12", "13", "16", "18")}
    assert hom.level_of(unit_only)["level"] == "L0"                                        # not even L1 without a real identity capture
    obs["coverage"]["11"] = {"kind": "real_fixture", "ref": "x/y.txt", "sha256": "0" * 64}
    obs["coverage"]["18"] = {"kind": "unit_test", "ref": "a/b_test.go::TestX"}
    assert hom.level_of(obs)["level"] == "L2"                                              # truncated output is our parser's reaction: a named unit test is enough for that one case
    obs["coverage"]["18"] = {"kind": "synthetic_fixture", "ref": "a/b.txt", "sha256": "0" * 64}
    assert hom.level_of(obs)["level"] == "L1"
    obs["coverage"]["18"] = {"kind": "unit_test", "ref": "a/b_test.go::TestX"}
    obs["coverage"]["11"]["kind"] = "real_fixture"
    obs["coverage"]["11"]["kind"] = "real_fixture"
    obs["certifications"] = [{"kind": "preview", "evidence_ref": "docs/x.md", "approved_by": "owner"}]
    assert hom.level_of(obs)["level"] == "L3"
    obs["certifications"].append({"kind": "provisioning", "evidence_ref": "docs/y.md", "approved_by": "owner"})
    assert hom.level_of(obs)["level"] == "L4"
    assert hom.level_of({**_dev(led, "C300")})["level"] == "L0"


@pytest.mark.parametrize("mutate", [
    lambda L: _dev(L, "MA5608T")["coverage"].update({"3": {"kind": "real_fixture", "ref": "../etc/passwd", "sha256": "0" * 64}}),
    lambda L: _dev(L, "MA5608T")["coverage"].update({"3": {"kind": "real_fixture", "ref": "a/b.txt", "sha256": "nothex"}}),
    lambda L: _dev(L, "MA5608T")["coverage"].update({"3": {"kind": "unit_test", "ref": "a/b_test.go"}}),
    lambda L: _dev(L, "MA5608T")["coverage"].update({"99": {"kind": "real_fixture", "ref": "a/b.txt", "sha256": "0" * 64}}),
    lambda L: _dev(L, "MA5608T")["coverage"].update({"3": {"kind": "screenshot", "ref": "a/b.png", "sha256": "0" * 64}}),
    lambda L: _dev(L, "MA5608T").update(certifications=[{"kind": "provisioning", "evidence_ref": "", "approved_by": "x"}]),
    lambda L: _dev(L, "MA5608T").update(driver_level="certified"),
    lambda L: L["devices"].append(copy.deepcopy(_dev(L, "MA5608T"))),
])
def test_a_broken_ledger_is_refused_whole(mutate):
    led = copy.deepcopy(_led())
    mutate(led)
    with pytest.raises(hom.LedgerInvalid):
        hom.validate(led)


@pytest.mark.skipif(not (ROOT / "agents/edge/internal/olt/driver.go").exists(), reason="repository files are not in this environment (the image carries only the API)")
def test_every_evidence_reference_exists_and_every_fixture_matches_its_hash_and_the_driver_level_matches_the_edge():
    led = _led()
    for d in led["devices"]:
        for n, c in d["coverage"].items():
            if c["kind"] == "unit_test":
                f, name = c["ref"].split("::")
                assert f"func {name}(" in (ROOT / f).read_text(encoding="utf-8"), (d["model"], n, c["ref"])
            else:
                assert hashlib.sha256((ROOT / c["ref"]).read_bytes()).hexdigest() == c["sha256"], (d["model"], n, c["ref"])   # a golden fixture edited by hand breaks here
    go = (ROOT / "agents/edge/internal/olt/driver.go").read_text(encoding="utf-8")
    reg = re.findall(r'\{"(\w+)", "([\w-]+)", "([\w.-]+)", Level(\w+),', go)
    for d in led["devices"]:
        row = next((r for r in reg if r[0] == d["vendor"] and d["model"].startswith(r[1]) and d["firmware"].startswith(r[2])), None)
        assert row is not None and row[3].lower() == d["driver_level"], (d["model"], row)   # the ledger cannot claim a driver level the Edge Registry does not hold


def _on(migrated, tenant):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'fleet_manager',true) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = true"), {"t": tenant})


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'fleet_manager'"))
        c.execute(text("DELETE FROM olts WHERE name LIKE 'HOM-%'"))


def test_the_endpoint_matches_registered_olts_to_the_ledger_and_marks_stale_and_unknown(client, seed, inv, migrated):
    h, hn1 = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")
    assert client.get("/v1/fleet/homologation", headers=h).json()["detail"] == "feature_disabled"
    _on(migrated, seed["A"])
    assert client.get("/v1/fleet/homologation", headers=hn1).status_code == 403
    for n in ("HOM-A", "HOM-B", "HOM-C", "HOM-D"):
        assert client.post("/v1/fleet/olts", headers=h, json={"name": n, "edge_id": str(inv["a1"]["edge"]), "vendor": "huawei"}).status_code in (200, 201)
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET model='MA5608T', firmware='MA5600V800R015C00', observed_at = now() - interval '5 minutes' WHERE name='HOM-A'"))
        c.execute(text("UPDATE olts SET model='MA5608T', firmware='MA5600V800R015C00', observed_at = now() - interval '3 hours' WHERE name='HOM-B'"))
        c.execute(text("UPDATE olts SET model='MA9999', firmware='X1', observed_at = now() WHERE name='HOM-C'"))
    body = client.get("/v1/fleet/homologation", headers=h).json()
    by = {o["name"]: o for o in body["olts"]}
    assert by["HOM-A"]["level"] == "L1" and by["HOM-A"]["stale"] is False
    assert by["HOM-B"]["level"] == "L1" and by["HOM-B"]["stale"] is True                  # an old read is stale, never "up"
    assert by["HOM-C"]["level"] == "não catalogado"                                        # a firmware the ledger does not name inherits nothing
    assert by["HOM-D"]["level"] == "ainda não lida" and by["HOM-D"]["stale"] is True
    assert [d["level"] for d in body["devices"]] == ["L1", "L0", "L0"] and body["stale_after_minutes"] == 60 and isinstance(body["connection_tests_24h"], dict)


def test_a_broken_ledger_answers_503(client, seed, inv, migrated, monkeypatch):
    _on(migrated, seed["A"])
    def boom():
        raise hom.LedgerInvalid("x")
    monkeypatch.setattr(hom, "load", boom)
    r = client.get("/v1/fleet/homologation", headers=hdr(client, "alice", seed, "A"))
    assert r.status_code == 503 and r.json()["detail"] == "homologation_ledger_invalid"


def test_the_counts_and_olts_never_mix_tenants_and_the_limit_of_an_hour_is_explicit(client, seed, inv, migrated):
    h = hdr(client, "alice", seed, "A")
    _on(migrated, seed["A"])
    with migrated.begin() as c:
        # tenant B has an OLT and three recent connection tests; tenant A has none
        b_olt = c.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level) VALUES (:t,:e,'HOM-B-OLT','huawei','identified') RETURNING id"), {"t": seed["B"], "e": inv["b1"]["edge"]}).scalar()
        for _ in range(3):
            c.execute(text("INSERT INTO olt_connection_tests (tenant_id, olt_id, job_id, outcome) VALUES (:t,:o,gen_random_uuid(),'submitted')"), {"t": seed["B"], "o": b_olt})
    body = client.get("/v1/fleet/homologation", headers=h).json()
    assert body["connection_tests_24h"] == {} and "HOM-B-OLT" not in {o["name"] for o in body["olts"]}
    with migrated.begin() as c:
        c.execute(text("DELETE FROM olt_connection_tests WHERE olt_id = :o"), {"o": b_olt})
        c.execute(text("DELETE FROM olts WHERE id = :o"), {"o": b_olt})
    # just inside and just outside the hour: 59 min is up to date, 61 min is stale
    assert client.post("/v1/fleet/olts", headers=h, json={"name": "HOM-E", "edge_id": str(inv["a1"]["edge"]), "vendor": "huawei"}).status_code in (200, 201)
    assert client.post("/v1/fleet/olts", headers=h, json={"name": "HOM-F", "edge_id": str(inv["a1"]["edge"]), "vendor": "huawei"}).status_code in (200, 201)
    with migrated.begin() as c:
        c.execute(text("UPDATE olts SET model='MA5608T', firmware='MA5600V800R015C00', observed_at = now() - interval '59 minutes' WHERE name='HOM-E'"))
        c.execute(text("UPDATE olts SET model='MA5608T', firmware='MA5600V800R015C00', observed_at = now() - interval '61 minutes' WHERE name='HOM-F'"))
    by = {o["name"]: o for o in client.get("/v1/fleet/homologation", headers=h).json()["olts"]}
    assert by["HOM-E"]["stale"] is False and by["HOM-F"]["stale"] is True


def test_a_truncated_olt_list_says_so(client, seed, inv, migrated, monkeypatch):
    from app.api import knowledge as api
    h = hdr(client, "alice", seed, "A")
    _on(migrated, seed["A"])
    for n in ("HOM-T1", "HOM-T2", "HOM-T3"):
        assert client.post("/v1/fleet/olts", headers=h, json={"name": n, "edge_id": str(inv["a1"]["edge"]), "vendor": "huawei"}).status_code in (200, 201)
    full = client.get("/v1/fleet/homologation", headers=h).json()
    assert full["olts_truncated"] is False and full["olts_total"] == len(full["olts"]) >= 3
    monkeypatch.setattr(api, "OLT_LIMIT", 2)
    cut = client.get("/v1/fleet/homologation", headers=h).json()
    assert cut["olts_truncated"] is True and len(cut["olts"]) == 2 and cut["olts_total"] == full["olts_total"]
