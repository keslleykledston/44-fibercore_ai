"""Owner CLI `onu-cpe-link-suggest` (ADR-0030 item 2a): records a SUGGESTED link with physical evidence; it never confirms."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import agent, hdr, login  # noqa: F401  (fixtures/helpers kept together with the other bench tests)

GOOD = "# H1 evidencia\n" + ("texto de evidência física do vínculo sem endereço nem credencial. " * 6)
REF = "docs/wiki/bench/H1-vinculo-teste-2026-11-01.md"


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'onu_cpe_links'"))
        c.execute(text("DELETE FROM onu_cpe_links WHERE cpe_id IN (SELECT id FROM cpes WHERE canonical_serial LIKE 'LNK-%')"))
        c.execute(text("DELETE FROM cpe_protocol_bindings WHERE cpe_id IN (SELECT id FROM cpes WHERE canonical_serial LIKE 'LNK-%')"))
        c.execute(text("DELETE FROM cpes WHERE canonical_serial LIKE 'LNK-%'"))
        c.execute(text("DELETE FROM onus WHERE serial LIKE 'LNKONU%'"))
        c.execute(text("DELETE FROM olts WHERE name = 'OLT-LNK'"))


def _ids(client, inv, seed, migrated):
    body = {"edge_id": str(inv["a1"]["edge"]), "observed_at": datetime.now(UTC).isoformat(), "cpes": [
        {"canonical_serial": "LNK-CPE-0001", "vendor": "ZTE", "model": "F670L", "firmware": "V9.0.11P1N10B",
         "binding": {"protocol": "tr069", "external_id": "lnk-ext-1", "connector_id": "c-lnk"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=agent(client, inv, "a1"), json=body).status_code == 202
    from tests.conftest import snap
    onus = [{"serial": "LNKONU0000001", "pon_path": "0/1/0", "status": "online", "rx_dbm": -21.5}]
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv, name="OLT-LNK", onus=onus)).status_code == 202
    h = hdr(client, "alice", seed, "A")
    cpe = next(c["id"] for c in client.get("/v1/cpes", headers=h).json() if c["canonical_serial"] == "LNK-CPE-0001")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        onu = c.execute(text("SELECT id FROM onus WHERE serial = 'LNKONU0000001'")).scalar()
    return str(onu), cpe


def _root(tmp_path, monkeypatch, content=GOOD, name="H1-vinculo-teste-2026-11-01.md"):
    root = tmp_path / "evidence"
    root.mkdir(exist_ok=True)
    (root / name).write_text(content, encoding="utf-8")
    monkeypatch.setenv("FIBERCORE_EVIDENCE_ROOT", str(root))
    return root


def test_owner_suggests_a_link_with_evidence_and_it_stays_suggested_until_a_person_confirms(client, seed, inv, migrated, admin_url, monkeypatch, tmp_path, capsys):
    import hashlib

    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    _root(tmp_path, monkeypatch)
    t = str(seed["A"])
    onu, cpe = _ids(client, inv, seed, migrated)
    args = ["onu-cpe-link-suggest", t, onu, cpe, "--evidence-ref", REF, "--by", "responsável"]
    cli.main(args)
    assert "suggested link" in capsys.readouterr().out
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t})
        row = c.execute(text("SELECT status, confidence, evidence, reviewed_by FROM onu_cpe_links WHERE onu_id = :o AND cpe_id = :c"), {"o": onu, "c": cpe}).one()
    assert row.status == "suggested" and row.reviewed_by is None and float(row.confidence) == 0.60
    assert row.evidence["rule"] == "owner_physical_evidence" and row.evidence["evidence_ref"] == REF and row.evidence["ambiguous"] is False
    assert row.evidence["evidence_sha256"] == hashlib.sha256(GOOD.encode()).hexdigest()   # the hash of the REFERENCED file
    cli.main(args)   # idempotent
    assert "already exists" in capsys.readouterr().out
    h = hdr(client, "alice", seed, "A")
    with migrated.begin() as c:
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled, updated_at) VALUES (:t,'onu_cpe_links',true,now()) ON CONFLICT DO NOTHING"), {"t": t})
    link_id = next(x["id"] for x in client.get("/v1/onu-cpe-links?status=suggested&limit=50", headers=h).json() if x["cpe"]["id"] == cpe)
    assert client.post(f"/v1/onu-cpe-links/{link_id}/confirm", headers=h).status_code == 200   # the normal review confirms it


def test_owner_link_suggest_refuses_bad_input(client, seed, inv, migrated, admin_url, monkeypatch, tmp_path):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(seed["A"])
    onu, cpe = _ids(client, inv, seed, migrated)
    root = _root(tmp_path, monkeypatch)
    base = ["onu-cpe-link-suggest", t, onu, cpe, "--by", "x"]
    with pytest.raises(SystemExit, match="docs/wiki/bench/H1"):
        cli.main(base + ["--evidence-ref", "docs/other.md"])
    with pytest.raises(SystemExit, match="docs/wiki/bench/H1"):
        cli.main(base + ["--evidence-ref", "docs/wiki/bench/../H1-x.md"])
    with pytest.raises(SystemExit, match="cannot read"):   # the referenced file does not exist under the root
        cli.main(base + ["--evidence-ref", "docs/wiki/bench/H1-nao-existe-2026-11-01.md"])
    real = tmp_path / "fora" / "H1-link-2026-11-01.md"   # a symlink under the root pointing outside is refused
    real.parent.mkdir()
    real.write_text(GOOD, encoding="utf-8")
    (root / "H1-link-2026-11-01.md").symlink_to(real)
    with pytest.raises(SystemExit, match="regular file"):
        cli.main(base + ["--evidence-ref", "docs/wiki/bench/H1-link-2026-11-01.md"])
    bad = {"curto": "curto"}
    for i, extra in enumerate((" 10.1.2.3", " 2001:db8:85a3:0:0:8a2e:370:7334", " 2001:db8::1", " ::1", " senha: x", " api_key = abc", " chave: abc")):
        bad[f"s{i}"] = GOOD + extra
    for name, content in bad.items():
        (root / f"H1-{name}-2026-11-01.md").write_text(content, encoding="utf-8")
        with pytest.raises(SystemExit, match="empty or carries"):
            cli.main(base + ["--evidence-ref", f"docs/wiki/bench/H1-{name}-2026-11-01.md"])
    (root / "H1-hora-2026-11-01.md").write_text(GOOD + " horário 16:04:40 e versão V9.0.11P1N10B e PON 0/0/14", encoding="utf-8")   # times and versions are not addresses
    cli.main(base + ["--evidence-ref", "docs/wiki/bench/H1-hora-2026-11-01.md"])
    with pytest.raises(SystemExit, match="not found"):
        cli.main(["onu-cpe-link-suggest", t, str(uuid4()), cpe, "--evidence-ref", REF, "--by", "x"])
    with pytest.raises(SystemExit, match="not found"):   # another tenant's CPE is invisible
        cli.main(["onu-cpe-link-suggest", str(seed["B"]), onu, cpe, "--evidence-ref", REF, "--by", "x"])
