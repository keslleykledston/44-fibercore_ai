# ADR-0025: Integração do Feature Pack SD-001 (Smart Diagnostics & Remediation) à base existente

Status: Proposed (aguarda aceite do Tech Lead) | Data: 2026-10-29 | Owner: equipe | Origem: pacote SD-001, gate B0 (`docs/feature-packs/SD-001/BASELINE_COMPATIBILITY_REPORT.md`)

## Contexto
O pacote SD-001 propõe diagnóstico remoto assistido e remediação controlada de CPE/ONU/Wi-Fi. A base já tem Visão 360, Diagnóstico guiado, motor de regras versionado (`diagnostic_runs` append-only, ADR-0024), NOC Command Center, Capability Registry (fatia mínima, ADR-0019), gate de jobs com aprovação e envelope assinado (`jobs.py`), flags por tenant (ADR-0023) e help-by-construction. O pacote usa nomes, caminhos e tabelas que colidem com o que existe (relatório B0, seção 3).

## Opções
A) Aplicar o pacote como está (tabelas/rotas/serviços novos): duplica aprovação, execução e `diagnostic_runs`; quebra testes e contrato publicado.
B) **Estender o existente**, acrescentando só o que falta, com os nomes e caminhos reais, e bloquear o que depende de dados/ADRs ausentes.
C) Ignorar o pacote: perde os contratos de evidência, a política default-deny e o plano de homologação.

## Decisão
Opção B, com estas regras:
1. SD-001 é identificador de funcionalidade; **nenhuma versão, tag ou sprint muda**.
2. `diagnostic_runs` e `/v1/diagnostics/runs` ficam como estão (execução de regras, síncrona, reproduzível). O ciclo de vida assíncrono do pacote vira recurso **novo** (`diagnostic_jobs`, `/v1/diagnostics/jobs`) que, ao concluir, gera uma `diagnostic_run`.
3. Aprovação e execução reutilizam `jobs`/`job_approvals`/`audit_log`; a única tabela nova de remediação é `action_proposals` (diff, impacto, risco, `proposal_hash`), e a aprovação passa a se vincular a esse hash.
4. Escopos: mapear para os existentes (`diagnostics:run`, `jobs:*`) e acrescentar só `diagnostics:run_active` e `diagnostics:propose`.
5. Eventos seguem a convenção do outbox (ADR-0007); nada de subjects novos antes de conferir o relay.
6. Sem unidade de deploy nova (estender `app/workers`); caminhos reais: `apps/api`, `agents/edge`, `contracts/`.
7. Flags `smart_diagnostics_*` entram em `features.py` com padrão **False**; módulo opcional `smart-diagnostics` no registry.
8. **Bloqueios explícitos:** leitura de árvore de parâmetros do CPE (WAN/PPPoE/Wi-Fi) só após ADR-SD-002 (lista de caminhos permitida + redação no Edge) **e** NBI do GenieACS fechado; copiloto só após ADR-0015/ADR-SD-006; USP após ADR-SD-005; testes ativos após ADR-SD-003; qualquer escrita real só com homologação por modelo/firmware e autorização operacional separada.

## Consequências
Primeiro PR de código (SD-PR-01) é apenas contratos e mocks, sem endpoint real nem migração. Testes: 2 tenants (RLS) em cada recurso novo, regressão dos 29+ testes do NOC e dos de `diagnostics`, validação de contratos em CI. Rollback: cada PR é aditivo (tabelas novas, flags desligadas). Se o Tech Lead preferir outro nome que não `diagnostic_jobs`, só o ADR e o contrato mudam.
