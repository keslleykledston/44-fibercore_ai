# QoS-001 — CURRENT_STATE (inspeção somente leitura, 2026-10-31)

Base: `main` com SD-001 Speed Diagnostics (ADR-0038) em código, implantado no LAB com a flag `speed_diagnostics` **desligada** e **nenhum teste de banda executado** (o gate está em `redirect_unverified`: a ONT de bancada SEGUE 3xx, ver `docs/wiki/bench/H-speed-sonda-3xx-eg8145v5-2026-10-31.md`). Pacote do adendo: `docs/addenda/v2.2-qos/reference/` (README, prompts, contratos, fixtures Q01–Q22).

## O que já existe e o QoS-001 deve reutilizar
| Peça | Onde | Estado |
|---|---|---|
| Leitura passiva de estado do CPE (cache do ACS) | `agents/edge/internal/nbi/params.go` (lista fechada de folhas), `POST /v1/edge/cpe-state` em `apps/api/app/api/cpe_state.py`, tabela `cpe_state` | 5 métricas: `wan_link_status`, `wan_connection_status`, `uptime_seconds`, `wifi_radio_enabled`, `wifi_channel` (ADR-SD-002). Cada uma com escopo fechado, valor tipado e `captured_at` |
| Leitura ativa `refresh` (getParameterValues, 1 CPE, ritmo 10 min/20 h) | Edge `nbi` + job assinado `refresh` (R0) | Implementada, `refresh_tasks` desligada por padrão; medida só na EG8145V5 |
| Óptica / PON da OLT | `onus.rx_dbm`, `pon_ports`, `onu_state_events`; coleta CLI/SNMP do Edge | Origem **OLT**, já coletada (775 ONUs) — nunca é `TR069` |
| Diagnóstico passivo e regras | `apps/api/app/core/diagnostic_jobs.py`, `app/api/diagnostic_jobs.py`, `app/core/diagnostics.py` (R-D001 PON, R-D002 WAN), contrato `contracts/sd001/evidence-envelope.schema.json`; ADR-0028 | `diagnostic_jobs` imutável, replay reprodutível; domínios `pon` e `wan`; Wi-Fi/LAN/Internet recusados (422) |
| Teste de banda (motor TR-143) | `apps/api/app/core/speed.py` + `app/api/speed.py` (`POST/GET /v1/cpes/{id}/speed/runs`), migração 0034/0035, Edge `internal/speed` + `internal/nbi/speed.go`, ADR-0038 | Único motor TR-143. Limites 1/CPE, 1/PON, 2/provedor sob lock consultivo; run groups por direção; resultado só contadores brutos + `compute()` |
| Catálogo de manobras de bancada e autorização de uso único | `apps/api/app/core/bench.py` (`BENCH_OPS`, gate), `app/api/bench_authorizations.py`, ADR-0030 | Ações no CPE só em alvo de bancada; `HOMOLOGATED_WRITES` vazio |
| Capability Registry | `apps/api/app/core/capabilities.py`, tabela `device_capabilities`, owner CLI `capability-set` | Por fabricante/modelo/firmware/protocolo/operação, com `identified|observed|certified` e evidência |
| Flags / permissões | `app/core/features.py` (`smart_diagnostics_jobs`, `smart_diagnostics_active_tests` (bloqueada até ADR-SD-003), `smart_diagnostics_copilot` (bloqueada), `speed_diagnostics`), `app/core/permissions.py` (`diagnostics:run`, `diagnostics:speed_run`) | RBAC por papel, matriz gerada |
| UX | `apps/web/src/components/OnuQuickInspector.tsx` (abas `resumo|aparelho|banda|historico`), `OnuWorkspace.tsx`, `SpeedTestSection.tsx`, `SourceChip.tsx`, `app/rede/onu/[id]/page.tsx`, `app/assinantes/diagnostico/[id]/page.tsx` | Sidebar recolhível já com a aba "Teste de banda" |
| Ajuda | `docs/help/how-to/rede/*.md` (inclui `testar-banda.md`), `docs/help/screenshot-manifest.yaml`, `apps/web/e2e/help-*.spec.ts` | Capturas reais por Playwright, validador `tests/validate_help.py` |

## O que NÃO existe (verificado por busca em `apps/`, `agents/`, `contracts/`)
`IPPing`, `NSLookup`, `TraceRoute`; métricas de Ethernet (velocidade/erros), CPU/memória, Wi-Fi (retries/associados/PHY); entidade de "suite" de qualidade; motor de hipóteses de qualidade (LAN_LINK_100M, WIFI_POTENTIAL, …); identificação genérica da **WAN de serviço** (hoje só a configuração local do Edge por dispositivo de bancada, `speed_wan_interface`); mapa TR-098 de Ping/DNS por modelo no registro; cartão "Qualidade do serviço"; permissões `diagnostics:quality_*`.

## Restrições herdadas que valem para o QoS
- Qualquer tarefa **ativa** num CPE (ping/DNS/traceroute escrevem `DiagnosticsState=Requested`) é uma escrita no aparelho: entra no catálogo de bancada (ADR-0030 + emenda), com autorização de uso único, e não no gate global (`HOMOLOGATED_WRITES` segue vazio).
- GenieACS só via NBI pelo Edge; a nuvem guarda **ids lógicos** de destino, nunca endereço (mesmo padrão do `speed_endpoints`).
- NBI 200/202 nunca é conclusão; resultado só com leitura posterior ao pedido; 202/ambíguo ⇒ remove a própria tarefa e não reenvia (medido: a EG8145V5 só atende o Connection Request às vezes).
- Ver `docs/operations/MONITORING.md` para recuperação e alertas.
