# Feature Pack SD-001 — Smart Diagnostics & Remediation

Este diretório guarda a integração do pacote **SD-001** à base existente. SD-001 é um identificador de funcionalidade: **não é versão do produto** e não substitui o Build Kit v2.2 (`docs/addenda/v2.2/`).

- `BASELINE_COMPATIBILITY_REPORT.md` — gate B0: o que já existe, o que colide, o que falta e em que ordem fazer.
- ADR de integração: `docs/wiki/adr/ADR-0025-integracao-do-feature-pack-sd-001.md` (Accepted).
- Pacote original: `FiberCore_FeaturePack_SD001_SmartDiagnostics.zip`, sha256 `92322ca29d59e914…` (42 arquivos conferidos contra o `MANIFEST_SHA256.txt`). Fica **fora** do repositório; arquivos dele só entram aqui por PR, um a um, depois de reconciliados (contratos são propostas, não fonte autoritativa).
- O protótipo `ux/diagnostic-prototype.html` do pacote é ilustrativo: nunca vira captura de manual (as capturas são Playwright reais da tela implementada).
- Toda escrita em equipamento real exige homologação por modelo/firmware e autorização operacional separada.

## Andamento
- SD-PR-00 (B0): relatório + ADR-0025 — feito; ADR **Accepted** em 2026-10-29.
- SD-PR-01: `contracts/sd001/` + `tests/fixtures/sd001/` + flags desligadas — feito (PR 47). Sem endpoint, migração ou evento.
- SD-PR-02 (reformulado): leitor passivo de parâmetros do CPE no Edge + ADR-SD-002 (PR 48). A extensão de `device_capabilities` segue pendente.
- Próximos: SD-PR-03 (`diagnostic_jobs` somente leitura) e o transporte `cpe_state` Edge→nuvem (migração) — este só faz sentido com dado; hoje o cache não tem WAN/Wi-Fi. Leitura da árvore de parâmetros do CPE (WAN/PPPoE/Wi-Fi) continua bloqueada por ADR-SD-002 (autorização de leitura do NBI dada em 2026-10-29; ainda falta a lista de caminhos permitidos + redação no Edge, e o NBI fechado pelo administrador).
