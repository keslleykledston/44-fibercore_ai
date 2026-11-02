# Auditoria do pacote "FiberCore OLT Multivendor AllInOne v2" (2026-11-02)

Origem: arquivo `FiberCore_FleetManager_Knowledge_OLT_ONU_ONT_VISUAL_COMPLETO_v2.zip` enviado pelo responsável (SHA-256 abaixo). O conteúdo foi tratado como DADO: extraído em pasta própria e vazia, nada dele foi executado.
Reprodução: `python3 -I scripts/audit_device_package.py <pasta-extraída> <zip> eeeb25248b6e67e6b5af6892b2f2a0668a3738ba7a2c61eed049a667c274d0aa` (sai 0 só se o zip tem esse SHA-256, a pasta é EXATAMENTE o conteúdo do zip — cada arquivo igual, nenhum a mais ou a menos, diretórios (inclusive vazios) iguais, e nomes de entrada na forma portátil canônica — e tudo abaixo confere). Os ativos auditados entram no repositório no PR1, onde os testes repetem a verificação de IDs, arquivos e SVG seguro.

## Resultado (saída do script)
```json
{
  "checksums": {
    "failed": 0,
    "listed": 204
  },
  "files": {
    "missing_by_design": [
      [
        "olt-huawei-ma5608t-interactive",
        "svg"
      ],
      [
        "olt-huawei-ma5608t-interactive",
        "png"
      ]
    ],
    "png": 69,
    "svg": 69,
    "unexpected_missing": []
  },
  "manifest": {
    "accuracy": {
      "generic_form_factor_not_model_exact": 41,
      "reference_drawing_requires_slot_card_verification": 1,
      "schematic_not_model_exact": 28
    },
    "by_type_status": {
      "olt/ART_READY_DRIVER_NOT_HOMOLOGATED": 28,
      "olt/REFERENCE_REUSE_EXISTING": 1,
      "onu_ont/ART_READY_NOT_LIVE_INTEGRATED": 41
    },
    "declared": 70,
    "entries": 70,
    "ids_sha256": "137e24fd46566587c3edab9440d60f89d9536209fd6f14a982eef8b5bb0b6571",
    "unique_ids": true,
    "vendors": [
      "datacom",
      "fiberhome",
      "huawei",
      "intelbras",
      "parks",
      "ubiquiti",
      "vsol",
      "zte"
    ]
  },
  "result": "OK",
  "svg_unsafe": [],
  "zip_bound_to_folder": {
    "different": [],
    "different_dirs": [],
    "members": 205,
    "same_as_folder": true
  },
  "zip_sha256": "eeeb25248b6e67e6b5af6892b2f2a0668a3738ba7a2c61eed049a667c274d0aa",
  "zip_sha256_expected_ok": true
}
```

## Leitura
- Integridade: todos os 204 arquivos listados em `SHA256SUMS.txt` conferem.
- 70 entradas no manifesto = 28 OLT (`ART_READY_DRIVER_NOT_HOMOLOGATED`) + 41 ONU/ONT (`ART_READY_NOT_LIVE_INTEGRATED`) + 1 referência (`REFERENCE_REUSE_EXISTING`: a MA5608T interativa, sem arquivo próprio; reaproveita o painel que o FiberCore já tem). 69 SVG e 69 PNG; IDs únicos; 8 fabricantes.
- Fidelidade declarada pelo próprio manifesto: nenhuma OLT tem mapa físico verificado (`unverified_from_inventory_required`); as ONU são formas genéricas por família. **Arte pronta não é suporte de driver.**
- Varredura de SVG (`<script`, handlers `on*=`, `javascript:`, `href` externo, `foreignObject`, `iframe`, `object`, `embed`): nenhum suspeito.
- Não coberto por esta auditoria: o conteúdo técnico de `knowledge/` (comandos, runbooks, recipes), que é referência a verificar por vendor/firmware no PR5, e as referências a fotos de fabricantes (`visual/sources/external-photography.json`), que **não** são copiadas.
