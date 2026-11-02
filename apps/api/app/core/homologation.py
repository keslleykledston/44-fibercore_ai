"""Homologation ledger (ADR-0041, PR6): the level (L0..L4) of each OLT model+firmware, COMPUTED from traceable evidence, never typed.

L0 cataloged: the device is in the ledger. L1 detected: identity and firmware come from a REAL capture. L2 monitoring validated: L1, the Edge driver is `observed` and the monitoring cases (board,
empty PON, ONU online/offline, pager) have a REAL capture and the truncated-output reaction is evidenced). L3/L4 need a recorded certification (preview / provisioning) with its evidence and approver: none exists yet, so nobody
is above L2. A synthetic fixture counts for nothing here. A new firmware never inherits a level: the ledger is keyed by vendor + model + exact firmware.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "knowledge_data" / "ledger.json"
KINDS = frozenset({"real_fixture", "synthetic_fixture", "unit_test"})
L2_DEVICE_CASES = (6, 11, 12, 13, 16)   # behaviour of the EQUIPMENT: only a real capture proves it (a unit test proves our code, not the device; a synthetic fixture proves nothing)
L2_CODE_CASES = (18,)                    # a truncated output is how OUR parser reacts to a cut listing: a named unit test is accepted, or a real capture
L2_CASES = L2_DEVICE_CASES + L2_CODE_CASES
CASE_NAMES = {6: "placa presente", 11: "PON sem ONU", 12: "ONU online", 13: "ONU offline", 16: "pager da CLI", 18: "saída truncada"}
REF_RE = re.compile(r"^[A-Za-z0-9_./-]+(::[A-Za-z0-9_]+)?$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LedgerInvalid(Exception):
    """The ledger broke an invariant: it is refused whole."""


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise LedgerInvalid(why)


def validate(led: dict) -> None:
    n_items = {c["n"] for c in led["checklist"]}
    _need(n_items == set(range(1, 23)), "ledger: the checklist must be the 22 reusable tests")
    seen = set()
    for d in led["devices"]:
        key = (d["vendor"], d["model"], d["firmware"])
        _need(key not in seen, f"ledger: duplicate device {key}")
        seen.add(key)
        _need(d["driver_level"] in {"identified", "observed"}, f"ledger: {key} has an unknown driver level")
        for n, c in d["coverage"].items():
            _need(n.isdigit() and int(n) in n_items, f"ledger: {key} covers an unknown test {n}")
            _need(c["kind"] in KINDS and bool(REF_RE.match(c["ref"])) and ".." not in c["ref"] and not c["ref"].startswith("/"), f"ledger: {key} test {n} has a bad evidence reference")
            _need((c["kind"] == "unit_test") == ("::" in c["ref"]), f"ledger: {key} test {n}: a unit test names a test, a fixture a file")
            _need(c["kind"] == "unit_test" or bool(HEX64.match(c.get("sha256", ""))), f"ledger: {key} test {n}: a fixture needs its SHA-256")
        for cert in d["certifications"]:
            _need(cert.get("kind") in {"preview", "provisioning"} and cert.get("evidence_ref") and cert.get("approved_by"), f"ledger: {key} has a certification without evidence or approver")


def level_of(d: dict) -> dict:
    cov = d["coverage"]
    real = lambda n: cov.get(str(n), {}).get("kind") in {"real_fixture", "unit_test"}  # noqa: E731
    realfx = lambda n: cov.get(str(n), {}).get("kind") == "real_fixture"  # noqa: E731
    certs = {c["kind"] for c in d["certifications"]}
    level, blockers = 0, []
    if realfx(3) and realfx(4):
        level = 1
        if d["driver_level"] == "observed" and all(realfx(n) for n in L2_DEVICE_CASES) and all(real(n) for n in L2_CODE_CASES):
            level = 2
            if "preview" in certs:
                level = 3
                if "provisioning" in certs:
                    level = 4
    if level == 0:
        blockers.append("identidade e firmware de uma captura REAL")
    elif level == 1:
        if d["driver_level"] != "observed":
            blockers.append("driver ainda `identified` (promover exige o checklist de DRIVER_SDK_INTERFACE.md)")
        blockers += [f"captura real de: {CASE_NAMES[n]}" for n in L2_DEVICE_CASES if not realfx(n)]
        blockers += [f"evidência de: {CASE_NAMES[n]}" for n in L2_CODE_CASES if not real(n)]
    elif level == 2:
        blockers.append("certificação de pré-visualização de perfil (L3)")
    elif level == 3:
        blockers.append("certificação de provisionamento com aprovação (L4)")
    return {"level": f"L{level}", "next_blockers": blockers}


@lru_cache(maxsize=1)
def load() -> dict:
    led = json.loads(DATA.read_text(encoding="utf-8"))
    validate(led)
    items = []
    for d in led["devices"]:
        cov = d["coverage"]
        items.append({"vendor": d["vendor"], "model": d["model"], "firmware": d["firmware"], "technology": d["technology"], "driver_level": d["driver_level"], "note": d["note"],
                      **level_of(d),
                      "coverage": [{"n": c["n"], "label": c["label"], "kind": cov.get(str(c["n"]), {}).get("kind", "not_covered"), "ref": cov.get(str(c["n"]), {}).get("ref")} for c in led["checklist"]]})
    return {"levels": led["levels"], "items": items}
