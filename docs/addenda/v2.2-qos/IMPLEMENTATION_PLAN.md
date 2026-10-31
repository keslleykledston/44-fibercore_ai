# QoS-001 — IMPLEMENTATION_PLAN (no máximo 2 PRs de código, todos atrás de flag OFF)

## PR 0 (este) — somente documentação
`CURRENT_STATE.md`, `GAP_MAP.md`, este plano, e a cópia de referência do pacote em `reference/`. Nenhuma linha de código, nenhum equipamento tocado.

## Decisões do responsável que mudam o desenho (perguntar antes do PR A, com recomendação)
1. **Ping/DNS fora da bancada.** Hoje toda escrita num CPE exige o alvo de bancada e autorização de uso único. Isso torna o RÁPIDO *ativo* inviável na operação normal. Recomendação: no PR A, ping/DNS entram **só na bancada** (consistente com o ADR-0030). Para produção, uma emenda posterior que homologue `IPPing`/`NSLookup` por modelo/firmware como operação de baixo risco (R1) depois da evidência de bancada. O RÁPIDO **passivo** (A1, A4, A5, A7) funciona em qualquer ONT com dados.
2. **WAN de serviço.** Sem regra para identificá-la, os testes ativos só rodam na bancada (onde o responsável nomeia a WAN) e a telemetria fora dela sai rotulada.
3. **Banda no COMPLETO.** Depende de resolver o `redirect_unverified` do SD-001 (ACL de saída real ou emenda); o QoS não contorna isso.

## PR A — backend, capacidade e Edge (migração 0036 aditiva)
- `apps/api/app/core/quality.py` (puro, sem relógio/banco/rede): contrato de medição, TTLs por grupo, estados sem zero falso, hipóteses determinísticas.
- Migração `quality_runs` (+ `speed_endpoints.target_kind` aceita `DNS`), RLS forçada, imutável, idempotência por `(tenant, usuário, Idempotency-Key)`.
- `app/api/quality.py`: `POST/GET /v1/cpes/{id}/quality/runs`, leitura de telemetria já retida (A1, A4, A5, A7), vínculo com o grupo de speed existente; flags e permissões novas; auditoria.
- Bancada: `ping_test`, `dns_test` em `BENCH_OPS`, com o mesmo lock/limites do SD-001 (`busy_reason`).
- Edge: `internal/nbi/diag.go` (um `setParameterValues` com `DiagnosticsState`, polling com prova de frescor, 202 ⇒ remove a própria tarefa), `speed.Catalog` ganha destinos DNS; `params.go` + `cpe_state.py` ganham `eth_link_status` e `eth_link_speed_mbps` (lista fechada espelhada, teste cruzado).
- Testes: Q01–Q22 que forem simuláveis com fake NBI e relógio controlado; regressão completa da API e do Go; contrato do envelope; cada correção de segurança com teste que falha sem ela.
- Codex até `approve`.

## PR B — sidebar, ajuda, changelog
- Aba "Qualidade" no inspetor e cartão no ONU 360 (componente novo `QualitySection.tsx`, padrão de `SpeedTestSection.tsx`), rotas BFF, e2e com servidor simulado.
- Ajuda: how-to, manifesto, capturas **reais** (estado bloqueado/telemetria com dados sintéticos) e cenários simulados rotulados; changelog; `QUALITY_HOMOLOGACAO.md`.
- Codex até `approve`.

## Mapa Q01–Q22
Automatizáveis em CI (PR A/B): Q01–Q10, Q11, Q13–Q16, Q18, Q19, Q21, Q22. Dependem de equipamento real (homologação, **não** declarar PASS antes): Q12 (óptica por perfil de classe), Q14 (mudança de firmware real), Q17, Q20, e a sequência CWMP real de ping/DNS por modelo.

## Rollback
Desligar `quality_diagnostics` (tudo) ou `quality_active_tests` (só ping/DNS) ou `quality_full`; SD-001 e ONU 360 seguem. Tabelas e colunas aditivas ficam inertes.
