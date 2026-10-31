"""Every acceptance document in the repository is the one whose hash the owner recorded (docs/wiki/bench/ACEITES.sha256). The gate never reads these files;
this is the integrity check of the readable copy (ADR-0038 amendment, option C)."""
import hashlib
import re
from pathlib import Path

from app.core import speed

BENCH = Path(__file__).resolve().parents[3] / "docs" / "wiki" / "bench"


def _recorded() -> dict[str, str]:
    out = {}
    for line in (BENCH / "ACEITES.sha256").read_text().splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line.strip())
        assert m, f"malformed line in ACEITES.sha256: {line!r}"
        out[m.group(2)] = m.group(1)
    return out


def test_every_acceptance_document_matches_its_recorded_hash_and_none_is_unrecorded():
    rec = _recorded()
    files = sorted(p.name for p in BENCH.glob("ACEITE-risco-3xx-*.md"))
    assert files == sorted(rec), "an acceptance document is missing from ACEITES.sha256 or the other way round"
    for name in files:
        assert hashlib.sha256((BENCH / name).read_bytes()).hexdigest() == rec[name], f"{name} changed after it was recorded"


def test_each_document_is_complete_by_the_same_rule_the_owner_cli_applies():
    for p in BENCH.glob("ACEITE-risco-3xx-*.md"):
        t = p.read_text()
        def field(k, t=t):
            return re.search(rf"^{k}:\s*(.+)$", t, re.M).group(1).strip()
        gaps = speed.acceptance_doc_gaps(p.name, t, vendor=field("Fabricante"), model=field("Modelo"), firmware=field("Firmware"),
                                         approved_by=field("Aprovado por"), accepted_on=field("Data"),
                                         endpoint_ids=[e.strip() for e in field("Destinos aceitos \\(ids lógicos, tipo CORE\\)").split(",")])
        assert gaps == [], gaps
