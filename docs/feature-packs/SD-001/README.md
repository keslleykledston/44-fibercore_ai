# Feature Pack SD-001 — Smart Diagnostics & Remediation

Este diretório guarda a integração do pacote **SD-001** à base existente. SD-001 é um identificador de funcionalidade: **não é versão do produto** e não substitui o Build Kit v2.2 (`docs/addenda/v2.2/`).

- `BASELINE_COMPATIBILITY_REPORT.md` — gate B0: o que já existe, o que colide, o que falta e em que ordem fazer.
- ADR de integração: `docs/wiki/adr/ADR-0025-integracao-do-feature-pack-sd-001.md` (Proposed).
- Pacote original: `FiberCore_FeaturePack_SD001_SmartDiagnostics.zip`, sha256 `92322ca29d59e914…` (42 arquivos conferidos contra o `MANIFEST_SHA256.txt`). Fica **fora** do repositório; arquivos dele só entram aqui por PR, um a um, depois de reconciliados (contratos são propostas, não fonte autoritativa).
- O protótipo `ux/diagnostic-prototype.html` do pacote é ilustrativo: nunca vira captura de manual (as capturas são Playwright reais da tela implementada).
- Toda escrita em equipamento real exige homologação por modelo/firmware e autorização operacional separada.
