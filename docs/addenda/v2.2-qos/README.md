# Adendo QoS-001 (FiberCore 2.2) — como ler esta pasta

- `CURRENT_STATE.md`, `GAP_MAP.md`, `IMPLEMENTATION_PLAN.md`: **autoridade deste repositório** (inspeção do código real, 2026-10-31).
- `reference/`: o pacote recebido, **sem alterações** (para rastrear o que foi pedido). Ele descreve o SD-001 como pronto para reuso; o repositório real tem diferenças. **Quando a referência divergir dos três arquivos acima, valem os três arquivos.**

## Divergências conhecidas (a referência assume X; o código tem Y)
| Referência diz | Realidade | Tratamento |
|---|---|---|
| "Reusar o lock/limites do SD-001; nunca duplicar locks" (`07_SEGURANCA_OPERACAO.md`, prompt mestre) | `busy_reason()` só conhece `speed_test_runs`; ping/DNS não ocupam o slot | **Reserva compartilhada por CPE** (banda, ping, DNS) é entrega obrigatória do PR A (GAP_MAP B5), com teste nos dois sentidos |
| "Ações só no Edge existente, com RBAC" | Toda escrita em CPE exige alvo de bancada + autorização de uso único (ADR-0030, `HOMOLOGATED_WRITES` vazio) | `ping_test`/`dns_test` só entram no catálogo por **emenda ao ADR-0030**; fora da bancada continuam bloqueados |
| "Resolver a WAN de serviço por configuração validada" | só existe `speed_wan_interface` na config local do Edge, um dispositivo de bancada | telemetria fora da bancada sai rotulada, sem atribuição ao serviço |
| "COMPLETO chama `SpeedDiagnostics.startRun`" | o serviço é `POST /v1/cpes/{id}/speed/runs`, e o gate está em `redirect_unverified` na EG8145V5 (a ONT segue 3xx) | COMPLETO guarda o `run_group_id` do SD-001 e mostra `speed=not_available` até o gate abrir |
| `diagnostics.quality.*` (permissões) | o projeto usa `recurso:ação` (`diagnostics:run`, `diagnostics:speed_run`) | `diagnostics:quality_read|quality_run|quality_run_full` |
| Flags `diagnostics.quality.*` | flags são nomes simples em `app/core/features.py` | `quality_diagnostics`, `quality_active_tests`, `quality_full` |
