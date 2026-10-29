# v2.2 — Análise de GAP e matriz de conflitos (estado real do repositório)

Checkpoint: `main` @ `5707795` (2026-10-29), Alembic `0014`, pytest 195, E2E 21 funcionais + capturas, Codex aprovado em todos os PRs mergeados. Estado de produção: **LAB** (nada de PRODUCTION_READY). O adendo é um **patch de requisitos**: nada abaixo foi sobrescrito; o pacote original está intacto em `docs/addenda/v2.2/` (checksums verificados por `tests/validate_addendum_v22.py`).

Legenda: **existe** = código + teste no repo; **parcial** = há base, falta parte do requisito; **falta** = nada; **bloqueado** = depende de decisão/dado que não temos.

## 1. Matriz de gaps (requisito novo × repositório)

| ID | Requisito v2.2 | Estado | Evidência real no repo | O que falta | Dependências | Decisão |
|---|---|---|---|---|---|---|
| FC22-001 | Audit + matriz de gaps | **este PR** | — | — | — | Entregue como documento; nada declarado pronto |
| FC22-002 | Capability Registry (modelo+firmware+protocolo, `unknown` por padrão) | **parcial** | Edge `olt.Registry` (vendor/model/firmware → `identified/observed/certified`); `olts.support_level`; `jobs.OPERATIONS` + `HOMOLOGATED_WRITES` (vazio, gate global); **contrato vigente documenta `GET /cpes/{cpeId}/capabilities` + schema `Capability`, mas não há handler no código** | Tabela no Cloud; implementar a rota **já documentada** (CPE) e a equivalente de OLT; cobertura TR-069/TR-369; gate por perfil nos jobs | 001 | **ADR-0019**; slice P0 desta entrega (tabela + leitura + UI mínima; escrita só por CLI do dono) |
| FC22-003 | Freshness/provenance em snapshots | **parcial** | `observed_at` em olts/onus/cpes/bindings; `_fresh()` (15 min) → `fresh/stale/unknown`; `DataFreshness` na UI; ONU 360 diz `source` | Campo `source`/`quality` padronizado nas respostas; `conflict` (2 fontes divergem); tabela `observations` | 001 | **ADR-0020**: envelope de proveniência nas respostas; `observations` só quando houver telemetria (P1) |
| FC22-004 | Customer Context API read-only | **implementado (PR 37, flags desligadas por padrão)** | `GET /v1/onus/{id}`, `/v1/onus/{id}/customer` (customers:read, auditado), `/v1/customers`, `/v1/associations` | Agregador centrado no cliente (`/v1/customers/{id}/context`); vínculo ONU↔CPE | 002, 003 | **ADR-0021** |
| FC22-005 | Subscriber 360 | **implementado (PR 38, flag desligada por padrão)** | Tela ONU 360 (`/rede/onu/[id]`) com Estado/Localização/Incidente/Assinante/Ações; how-to `rede/onu-360` | Entrada por cliente/contrato; abas Conexão/Óptica/Wi-Fi/Cliente/Histórico/Ações; CPE; timeline | 004 | Evoluir a ONU 360 (mesma rota), não criar tela paralela |
| FC22-006 | Diagnostic Rule Engine determinístico | **parcial** | Regra `pon_mass_outage` fixa em `app/api/noc.py` (ADR-0018: janelas, razões, `evidence`) | Registro de regras versionadas, `diagnostic_runs`, saída `observed/inferred/unknown` | 002, 003, 004 | Extrair a regra atual como R-D001 v1 (sem mudar comportamento) |
| FC22-007 | Guided Troubleshooting N1 | **falta** | — | Stepper + evidências + resumo p/ ticket | 006 | S2 |
| FC22-008 | Incidente agrupado PON/OLT com supressão por collector down | **existe** (validar) | ADR-0018; `edge_silent`; alerta de Edge offline; `dedupe_key`; `incident_onus`; testes em `test_noc.py` | Mapear cada caso a AC-004/AC-009; R-D003/R-D004 explícitas | — | Só validar e documentar |
| FC22-009 | NOC Command Center | **parcial** | `/noc` fila de incidentes (edge_silent, reconhecimento) | Prioridade/impacto (nº de clientes afetados via associações), drawer, ≤4 KPIs | 008, 004 | S2 |
| FC22-010 | Network Explorer POP/OLT/PON/CTO/ONU | **falta** | Há `olts`, `pon_ports`, `onus`; **não há CTO/POP** | Entidades CTO/POP, `network_links` com evidência/confiança, resolução manual | 003 | S3; sem inventar topologia |
| FC22-011 | Optical Health score | **bloqueado** | Só `onus.rx_dbm` pontual (sem histórico/flaps/erros) | Série temporal, limiares por classe óptica homologada, ADR de pesos | 002, 003, ADR-0022 | Fica `insufficient_data` até haver dados |
| FC22-012 | Home Experience score | **bloqueado** | Edge lê só `_id,_lastInform,_deviceId` do NBI (projeção mínima por segurança) | Leitura de parâmetros Wi-Fi/WAN por perfil certificado, com redação | 002, ADR-0022 | Ver conflito C-09 |
| FC22-013 | Wi-Fi Experience (UI) | **falta** | — | Tela só com dado observado | 011/012 | S3 |
| FC22-014 | Workflow Definition Registry + preview | **parcial** | `jobs.OPERATIONS`, `POST /v1/jobs/preview`, aprovações (R2 não auto-aprova, R3 dois), TTL, nonce, envelope Ed25519, pós-check | Catálogo versionado de definições com requisitos de capability; dry-run com diff redigido | 002 | Reusar o motor de jobs (sem `/workflow-previews` novo) |
| FC22-015 | Mutation lock TR-069/USP | **parcial** | Idempotência + CAS de estados; **USP não implementado** (ADR-0015) | Exclusão mútua por dispositivo/capability | USP | AC-011 só quando houver segundo protocolo; lock por CPE no motor de jobs antes |
| FC22-016 | Module health/version/changelog UX | **parcial** | `/v1/platform/modules`, `/versions`, aba Administração › Módulos | Changelog por módulo, canary | — | S4 |
| FC22-017 | Help screenshots/How-to por tela | **existe** (prática) | `validate_help.py`, manifesto, `help-screenshots.spec.ts`, 10 artigos publicados | Manter como gate de cada PR de tela | — | Já é regra; segue |
| FC22-018 | Copilot read-only | **bloqueado** | ADR-0015 adia; `docs/ai/COPILOT_SPEC.md` | Tudo | 004, 006 | Trilha posterior (P2) |
| (DoD) | **Feature flag por tenant** | **implementado (PR 36)** — antes: falta | Só `feature_flag` global por módulo em `configs/modules.yaml` | Flags por tenant | — | **ADR-0023**; sem isso, DoD da v2.2 fica *parcial* e declarado |

## 2. Matriz de conflitos (adendo × repositório)

| # | Ponto | Adendo diz | Repo faz | Decisão |
|---|---|---|---|---|
| C-01 | Prefixo de API | `/api/v1` | **Público** `/api/v1/*`; **interno** do core `/v1/*` (o proxy faz `uri strip_prefix /api`, `infra/deploy/Caddyfile.upstream`; ADR-0012). Os contratos listam caminhos relativos ao servidor público | Sem conflito; validador confere código (`/v1`) e proxy (strip) separadamente |
| C-02 | `X-Workspace-ID` | obrigatório | Opcional com 1 só membership; valida contra memberships | Manter o do repo (compatível) |
| C-03 | `/devices/{id}` | recurso único | **Não existe `devices`**: ids em `olts`, `cpes`, `onus`; o contrato vigente já tem `/cpes/{cpeId}/capabilities` | **Descartar `/devices/{id}`**: implementar a rota CPE já documentada + `/olts/{oltId}/capabilities`; ONU usa o perfil da sua OLT |
| C-04 | `Observation.quality` | `fresh/stale/unknown/conflict` | `fresh/stale/unknown` | Adicionar `conflict` só quando houver 2ª fonte (ADR-0020) |
| C-05 | Customer Context | `GET /customers/{id}/context` | `/v1/customers` lista com auditoria; dado pessoal só `customers:read` | Sub-rota nova; mantém RBAC + auditoria de PII (ADR-0021) |
| C-06 | `POST /diagnostics/runs` | responde 200 | POST que cria devolve 201 + id | 201 com id da execução (auditável) |
| C-07 | `/workflow-previews` | rota nova | `POST /v1/jobs/preview` já faz preview/aprovação | **Não duplicar**: definições são catálogo; execução segue no motor de jobs |
| C-08 | Eventos `*.v1` | tipos como `device.capabilities.changed.v1` | Outbox: `event_type` + `schema_version` em coluna | Manter nomes sem sufixo; versão em `schema_version`; envelope v2.2 mapeado (ver RECONCILED_API) |
| C-09 | Wi-Fi/QoE × segurança do Edge | ler Wi-Fi/WAN | NBI lido com projeção mínima **sem árvore de parâmetros** (sem PSK/PPPoE); NBI do GenieACS real está sem autenticação | Só caminhos de parâmetro **allowlist por perfil certificado** + redação; **bloqueado** até FC22-002 e fechamento do NBI |
| C-10 | Risco R0–R3 | R0–R3 | Idem em `jobs.OPERATIONS` | Sem conflito |
| C-11 | Certificação | `identified/observed/certified` | Idem em `support_level` | Sem conflito; novo eixo `support: supported/unsupported/unknown` |
| C-12 | Edge offline ≠ ONU offline | obrigatório | Implementado (ADR-0018, `edge_silent`) | Sem conflito |
| C-13 | Nome "Subscriber 360" × "ONU 360" | Subscriber 360 | Tela ONU 360 já publicada (`rede/onu-360`) | Evoluir em lugar; slug novo `assinantes/visao-360` quando a visão por cliente existir; manter o antigo |
| C-14 | Lovable para UX | usar Lovable | Política: UI local salvo lote visual; proposta Lovable anterior não integrada | **Um** pedido em lote ao iniciar FC22-005 (sem segredos), com `UX_HANDOFF.md` |
| C-15 | PII no contexto | exibir cliente | Dado pessoal só com `customers:read`, auditado, nunca em log/captura | Mantido; capturas só com dados sintéticos |
| C-16 | Identidade ONU×CPE | identidade única | Sem vínculo ONU↔CPE; `cpes.canonical_serial` ≠ `onus.serial` por definição | **ADR-0021**: vínculo explícito (evidência+confiança), nunca por igualdade de string |
| C-17 | Migração | expand/contract | Alembic aditivo; backup + restore verificado antes de migrar | Mantido |
| C-18 | `unknown` | nunca virar offline | ONU `status` já tem `unknown` | Mantido; teste existente |

| C-19 | Contrato × código (deriva existente) | — | Contrato vigente documenta e o código **não** implementa: `GET/POST /integrations/erp`, `POST /integrations/erp/{erpId}/sync`, `POST /copilot/suggestions`. O código tem `GET /v1/auth/workspaces` que o contrato **não** documentava | `/auth/workspaces` passou a constar no contrato (este PR). As 4 rotas restantes documentadas e não implementadas (a de capabilities do CPE foi implementada no PR 35) ficam **registradas como deriva conhecida**; o validador falha se surgir deriva nova |

## 3. Proposta de implementação incremental

1. **PR 34 (este)** — só docs/contratos/fixtures/teste de schema; sem código de produto.
2. **PR 35 — FC22-002, fatia mínima** — migração `device_capabilities` (RLS, CHECKs, default `unknown`), `GET /v1/cpes/{cpeId}/capabilities` (já documentada no contrato, sem handler) e `GET /v1/olts/{oltId}/capabilities`, CLI do dono para registrar evidência, bloco "Capacidades" no card **Ações** da ONU 360, testes (isolamento A/B, `unknown` padrão, escrita nunca liberada), how-to + capturas atualizados, Codex.
3. **S1** — FC22-003 (envelope `source`/`quality`), 004 (context + vínculo ONU↔CPE), 005 (Subscriber 360; Lovable em lote).
4. **S2** — 006 (R-D001 extraída, runs), 007, 009; 008 validada.
5. **S3/S4** — 010–013 só com dado real; 014–016.

Cada PR: API + DB + teste + manual + capturas Playwright reais (1440×900 e 390×844) + parecer Codex; nada é marcado como feito sem esses itens.