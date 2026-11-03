#!/usr/bin/env python3
"""Gera `apps/api/app/knowledge_data/ledger.json`: o livro-razão de homologação (ADR-0041 PR6). Cada cobertura aponta para uma fixture REAL ou sintética (com SHA-256) ou para um teste
nomeado; o NÍVEL (L0..L4) nunca é digitado: é calculado por `app/core/homologation.py` a partir disto. Uso: python scripts/gen_homologation_ledger.py (reescreve o arquivo)."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLT = "agents/edge/internal/olt"
CHECKLIST = ["SSH/TLS host key", "SNMPv3 auth", "Identidade", "Firmware", "OID", "Placa presente", "Slot vazio", "PON 0-/1-based", "PON fisicamente UP", "PON desligada administrativamente",
             "PON sem ONU", "ONU online", "ONU offline", "ONU stale", "OLT inalcançável", "Pager da CLI", "Idioma/locale da saída", "Saída truncada", "Colunas ocultas",
             "Perfil já existe", "ID de perfil em conflito", "Perfil em uso por outras ONUs"]


def fx(path: str, kind: str = "real_fixture") -> dict:
    p = ROOT / path
    return {"kind": kind, "ref": path, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def ut(path: str, name: str) -> dict:
    assert f"func {name}(" in (ROOT / path).read_text(encoding="utf-8"), (path, name)
    return {"kind": "unit_test", "ref": f"{path}::{name}"}


R015 = f"{OLT}/testdata/huawei_ma5608t/MA5600V800R015C00"
DEVICES = [
    {"vendor": "huawei", "model": "MA5608T", "firmware": "MA5600V800R015C00", "technology": "gpon", "driver_level": "identified",
     "note": "Capturas reais de 2026-10-28 e 2026-11-02 (uma OLT de laboratório). Falta uma PON vazia (item 11): as 32 PONs têm de 6 a 60 ONUs.",
     "coverage": {
         "1": ut(f"{OLT}/ssh_test.go", "TestSSHRejectsWrongHostKeyBadPasswordAndMissingPin"),
         "3": fx(f"{R015}/display_version.txt"), "4": fx(f"{R015}/display_version.txt"),
         "5": ut(f"{OLT}/huawei_snmp_test.go", "TestSNMPPonIfIndexFormulaAndRefusals"),
         "6": fx(f"{R015}/board_0.txt"), "8": fx(f"{R015}/ont_info_14_all_paged.txt"),
         "12": fx(f"{R015}/ont_info_14_all_paged.txt"), "13": fx(f"{R015}/register_info_14_0_offline_dying_gasp.txt"),
         "15": ut("agents/edge/internal/collector/olt_test.go", "TestAFailedSNMPCollectionLeavesTheDeviceAloneForTheCooldown"),
         "16": fx(f"{R015}/ont_info_5_all_paged.txt"),
         "18": ut(f"{OLT}/huawei_r015_test.go", "TestR015IncompleteOrInconsistentListingIsNeverVerified")},
     "certifications": []},
    {"vendor": "huawei", "model": "MA5800", "firmware": "R018", "technology": "gpon", "driver_level": "identified",
     "note": "Só fixtures sintéticas: nenhuma saída de equipamento real.",
     "coverage": {"3": fx(f"{OLT}/testdata/huawei_ma5800/R018/display_version.txt", "synthetic_fixture"), "4": fx(f"{OLT}/testdata/huawei_ma5800/R018/display_version.txt", "synthetic_fixture"),
                  "16": fx(f"{OLT}/testdata/huawei_ma5800/R018/ont_info_summary_paginated_0_1_0.txt", "synthetic_fixture")},
     "certifications": []},
    {"vendor": "zte", "model": "C300", "firmware": "V2.1", "technology": "gpon", "driver_level": "identified",
     "note": "Só fixtures sintéticas: nenhuma saída de equipamento real e nenhuma OLT ZTE no laboratório.",
     "coverage": {"3": fx(f"{OLT}/testdata/zte_c300/V2.1/show_version.txt", "synthetic_fixture"), "4": fx(f"{OLT}/testdata/zte_c300/V2.1/show_version.txt", "synthetic_fixture")},
     "certifications": []},
]
out = {"version": "1.0", "levels": ["L0", "L1", "L2", "L3", "L4"], "checklist": [{"n": i + 1, "label": t} for i, t in enumerate(CHECKLIST)], "devices": DEVICES}
(ROOT / "apps/api/app/knowledge_data/ledger.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("ok:", len(DEVICES), "equipamentos")
