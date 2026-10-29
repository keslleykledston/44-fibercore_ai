# SD-001 — BASELINE_COMPATIBILITY_REPORT (gate B0)

**Status:** relatório de reconciliação. Nenhum código, migração, contrato ou configuração do produto foi alterado por este trabalho.
**Aprovação do Tech Lead:** PENDING (decisões D-1 a D-6 abaixo; os padrões recomendados valem até alguém decidir o contrário).

## 1. Identificação

| Item | Valor |
|---|---|
| Repositório | `keslleykledston/44-fibercore_ai` (remoto `origin`), checkout `44-FiberCore`. O pacote cita `120-OLT_SaaS` como destino; **este é o repositório real do projeto** |
| Branch / commit | `main` @ `db78068`; sem tags; versão do produto inalterada |
| Build Kit v2.2 original | `FiberCoreAI_BuildKit_v2_Claude_Codex_Lovable.zip` na raiz (SHA em `SHA256SUMS.txt`) e adendo v2.2 em `docs/addenda/v2.2/` (README, GAP_ANALYSIS, RECONCILED_API, BACKLOG_V2_2, ACCEPTANCE_MATRIX) |
| Pacote SD-001 | `FiberCore_FeaturePack_SD001_SmartDiagnostics.zip` (sha256 `92322ca29d59e914…`); os 42 arquivos do manifesto conferem com `MANIFEST_SHA256.txt`; extraído **fora** do checkout; nenhum script do pacote foi executado |
| Estado real (2026-10-29) | pytest 251 passed; Playwright 49 passed; `go test ./...` PASS; ruff/tsc/validate_* PASS; Alembic 0018; estado do ambiente: LAB (nenhum estado de produção declarado) |
| Comandos de inspeção | `git status/branch/log/tag`; leitura de ADR-0001…0024, `configs/modules.yaml`, `contracts/*`, `apps/api/alembic/versions`, `apps/api/app/{api,core,workers}`, `agents/edge/internal/*`, `docs/wiki/IMPLEMENTATION_STATUS.md`, `docs/product/ROADMAP_BACKLOG.md`, `.agent-context/*` |

## 2. Matriz de capacidades (template do pacote)

Legenda: `implemented_verified` · `partially_implemented` · `specified_only` · `absent` · `incompatible`.

| Capability | Status verificado | Arquivo / endpoint / tela atual | Evidência de teste | Delta SD-001 | Classe |
|---|---|---|---|---|---|
| Subscriber 360 | **implemented_verified** (FC22-005) | `apps/web/src/app/assinantes/[id]/page.tsx`; `GET /v1/customers/{id}/context`; flags `subscriber_360`+`customer_context` | `tests/test_inventory_context.py`; E2E Visão 360 com axe e capturas reais; how-to `assinantes/visao-360` | aba/atalho "Diagnóstico completo" reaproveitando o bloco de proveniência | extend |
| Guided Troubleshooting | **implemented_verified** (FC22-007, `cac16fe`) | `/assinantes/diagnostico/[id]`, `lib/troubleshoot.ts`, `POST /v1/diagnostics/runs` com escopo `onu_id` | `test_inventory_diagnostics.py`; E2E; Codex approve (5 rodadas) | passos automáticos de WAN/LAN/Wi-Fi quando houver fonte | extend (bloqueado por dados, §4) |
| NOC Command Center | **implemented_verified** (FC22-009, `8d61560`) | `/noc`, `GET /v1/incidents(?order=priority)`, `/incidents/{id}`, `/ack`, painel lateral | `test_noc.py`, `test_noc_command_center.py`; E2E | `stop_on_mass_outage` da política SD-001 consome "PON com incidente aberto" daqui | reuse |
| Capability Registry | **partially_implemented** (FC22-002, ADR-0019) | migração 0015 `device_capabilities`; `app/core/capabilities.py`; `GET /v1/cpes/{id}/capabilities`, `/olts/{id}/capabilities`; CLI `capability-set`; flag `capability_registry` | `test_inventory_capabilities.py` | `parameter_paths`/`path_candidates`, TTL, prova de laboratório; alimentação pelo Edge e ligação ao gate de jobs (já listadas como **não feitas** no ADR-0019) | extend |
| Wi-Fi Experience/QoE | **absent / blocked** (ADR-0022) | — (a API responde `insufficient_data` por desenho) | — | telemetria de estação, interferência, testes CPE × dispositivo | new, **bloqueado por dados** |
| Automation Studio | **partially_implemented** | `apps/api/app/api/jobs.py` + migração 0008: preview→submit→approve→dispatch (envelope Ed25519)→resultado; `job_approvals`; `HOMOLOGATED_WRITES` vazio; `agents/edge/internal/jobs` | `test_jobs.py` | intents tipados com parâmetros, diff, pré/pós-check, catálogo de operações (FC22-014/015/016 ainda não feitos); hoje `preview` **rejeita qualquer parâmetro** por desenho | extend |
| AI Copilot read-only | **specified_only** (ADR-0015: adiado) | `docs/ai/COPILOT_SPEC.md`; módulo `copilot` com `feature_flag: false` | — | contrato de saída estruturado evidence-linked (`ai-diagnostic-output.schema.json`) | blocked (ADR-SD-006: provedor LLM + LGPD) |
| Help-by-construction | **implemented_verified** (ADR-0013) | `/ajuda`, `docs/help/how-to/**`, `tests/validate_help.py`, capturas Playwright 1440×900 e 390×844 | E2E `help-screenshots.spec.ts` | how-to + capturas reais para cada tela SD-001 | reuse |
| Release Center | **specified_only** (`docs/operations/RELEASE_CENTER.md`, ADR-0015) | — | — | divulgação/rollout SD-001 | blocked (não existe; não criar por causa do SD-001) |

## 3. Sobreposições com nome ou semântica colidindo (pontos de incompatibilidade)

| # | Pacote propõe | Já existe | Veredito | Recomendação |
|---|---|---|---|---|
| C-1 | `diagnostic_runs` com ciclo de vida (`queued→collecting→…→completed/partial/failed`), `POST /diagnostics/runs` (202 assíncrono), `GET /diagnostics/runs/{id}` | `diagnostic_runs` (migração 0018) **append-only** (app só INSERT/SELECT, RLS forçada), `POST /v1/diagnostics/runs` **síncrono** (regra pura R-D001 v1), `GET /diagnostics/runs/{id}` com `reproducible`; ADR-0024 | **incompatible** como escrito: mesmo nome, outra semântica; a tabela existente proíbe UPDATE, logo não comporta estados | manter o existente como **execução de regras** (R0, reproduzível). Criar o ciclo assíncrono como **recurso novo** (`diagnostic_jobs`, `/v1/diagnostics/jobs`) que, ao concluir, **gera** uma `diagnostic_run` (a RCA determinística já existe). Nenhuma tabela ou rota existente é renomeada |
| C-2 | tabelas `diagnostic_measurements`, `diagnostic_findings` | `findings` já fazem parte do JSON de `diagnostic_runs`; proveniência por bloco (ADR-0020) | **partially overlapping** | `diagnostic_measurements` é **new** (evidência bruta normalizada com fonte+frescor); `findings` seguem em `diagnostic_runs` até haver necessidade de consulta relacional (ADR) |
| C-3 | `approval-service`, `action_approvals`, `action_executions`, `operation_audits` | `job_approvals` (único por job+aprovador, solicitante ≠ aprovador, R3 = 2 aprovadores distintos, expira), `jobs.result`, `audit_log` (append-only) e envelope assinado com nonce, TTL 15 min e `intent_hash` | **duplicação** se criado como no pacote | **reutilizar** o gate de jobs: `action_proposals` é a única tabela nova (diff/impacto/risco/hash); aprovação e execução continuam em `jobs`/`job_approvals`/`audit_log`. Falta o vínculo aprovação↔hash da **proposta** (hoje o hash é do job): estender, não recriar |
| C-4 | escopos `diagnostics:read/run_passive/run_active/propose`, `remediation:approve:r2/r3/execute`, `audit:read` | `diagnostics:run`, `jobs:request/read/approve`, `inventory:read`, `incidents:ack`, `audit` (via `audit_log`) | **parcial** | mapear: `diagnostics:run`≈`run_passive`; adicionar **apenas** `diagnostics:run_active`, `diagnostics:propose` e a aprovação por classe de risco (hoje `Operation.risk` R0–R3 + `approvals`). Nada de renomear |
| C-5 | eventos `fibercore.diagnostics.requested.v1` etc. (3 canais AsyncAPI) | outbox + JetStream (ADR-0007); tipos atuais `incident.opened/resolved`, `olt.snapshot_ingested`, `job.dispatched` | **naming divergente** | seguir a convenção existente (`diagnostic_job.requested`, `remediation.proposed` …) e só então publicar no AsyncAPI; confirmar o subject real no relay antes |
| C-6 | caminhos `apps/api-core`, `agents/fiber-agent`, `services/automation-engine`, `services/diagnostics-worker`, `apps/ai-copilot`, `packages/contracts` | reais: `apps/api/app/{api,core,workers,events,integrations}`, `agents/edge`, `apps/api/app/api/jobs.py`, `contracts/` | **incompatible (paths)** | usar os caminhos reais; **nenhuma unidade de deploy nova** (o próprio ADR-SD001 recomenda) → ADR-SD-001 = "estender workers existentes" |
| C-7 | flags `smart_diagnostics.passive/active_tests/ai_analysis/remediation_*` | flags por tenant (`features.py`, ADR-0023, CLI `feature-set`) | **reuse** | acrescentar chaves ao `FEATURES` (padrão **False**); módulo opcional `smart-diagnostics` em `configs/modules.yaml` com `failure_mode` isolado |
| C-8 | `configs/operation-policy.example.yaml` (default-deny) | `HOMOLOGATED_WRITES = frozenset()`, `_blocked_reason`, ADR-0010 | **already satisfied** | não instalar o YAML; as regras viram checagens do policy engine determinístico em código |
| C-9 | contrato OpenAPI próprio (`/devices/{id}/capabilities`, `/remediations/proposals/{id}/approvals` …) | `contracts/fibercore-v2.openapi.yaml` já tem `/cpes/{id}/capabilities`, `/jobs/*`, `/diagnostics/*` | **merge aditivo** | mesclar só rotas novas; `/devices/{id}/capabilities` duplica `/cpes/{id}/capabilities` → **não criar** |

## 4. Lacunas reais que bloqueiam o escopo do pacote (dados e fontes)

| Escopo SD-001 | Fonte necessária | Estado real | Classe |
|---|---|---|---|
| PPPoE / WAN / DNS / contadores do CPE | árvore de parâmetros TR-098/181 via NBI | o coletor lê `_id,_lastInform,_deviceId` **de propósito** (sem árvore → nenhum PSK/PPPoE sai do site). Ampliar exige **lista de caminhos permitida + redação no Edge** | **new + blocked por ADR-SD-002** e revisão de segurança |
| Wi-Fi rádio/clientes | idem | ausente | blocked (idem) |
| Óptica lado ONU | `rx_dbm` por ONU (OLT Huawei MA5608T R015) | **existe** (CLI e SNMP), driver ainda `identified` (não `observed`) | reuse |
| Óptica lado OLT (Rx na OLT) | coluna "OLT Rx ONT power" | **não coletada** (driver não envia) | new (depende de captura real) |
| Causa de queda (dying-gasp/LOS) | SNMP `46.1.24` / `register-info` | mapeada no driver SNMP | reuse |
| Sessão PPPoE / BNG | integração com BNG/BRAS | ausente | absent |
| Plano/contrato ERP | importação CSV | existe (status e documento só HMAC+last4) | reuse |
| TR-369/USP | controller | ausente (ADR-0015) | blocked |
| Testes ativos (ping/traceroute/banda/TR-143) | operações tipadas + servidor de teste + quotas | ausentes; `jobs.preview` não aceita parâmetros | new (ADR-SD-003) |
| Escrita em CPE/ONU/OLT | homologação por firmware + aprovação | `HOMOLOGATED_WRITES` vazio; nada homologado | blocked (autorização operacional **separada**) |

**Fatos de ambiente relevantes (2026-10-29):** o Edge do host do GenieACS está ligado à OLT em **somente leitura**, com guard de ritmo (intervalo, resfriamento, instância única; PR 43/44). O NBI do GenieACS segue sem autenticação e exposto na rede do host porque a conta SSH do projeto não tem root (runbook em `docs/operations/GENIEACS_NBI_HARDENING.md`). Isso conflita com a restrição do pacote "não expor ACS NBI" e deve ser fechado antes de qualquer leitura de árvore de parâmetros (D1).

## 5. Reconciliação por ponto do pacote

| Tema do pacote | Resultado |
|---|---|
| Sem nova versão / sem release v2.2 / sem reiniciar sprints | Cumprido: nenhuma tag, nenhum bump, backlog FC22-001…009 intocado; SD-001 entra como **tarefas SD-001 ligadas ao backlog** |
| LLM nunca executa nem autoriza | Alinhado a ADR-0010 (write gate) e ao desenho do jobs; reforçar com teste no D4 |
| Read-only por padrão | Alinhado (Edge só leitura; `allowed_operations` no Edge limitado a `collect`/`refresh`) |
| Capacidade por modelo+firmware+transporte | `device_capabilities` já tem vendor/model/firmware/protocol/operation; falta `parameter_paths` e TTL |
| 2 tenants RLS em todo PR | Já é regra de teste do repo (`test_auth_rls`, cada módulo novo) |
| Screenshots Playwright reais | Pipeline existente (`SCREENSHOT_AND_HOWTO_PIPELINE.md`); o `ux/diagnostic-prototype.html` do pacote é **ilustrativo e não será usado como captura** |
| Lovable (UX) | 1 pedido em lote por tela; só referência visual; nunca segredos |
| Codex | revisão adversarial obrigatória por PR; `PASS/WARN/BLOCK` mapeado para approve / needs-attention; **nunca simular aprovação** |

## 6. Arquivos que NÃO devem ser tocados

Migrações `0001`…`0018`; `app/core/diagnostics.py` (R-D001 v1 é imutável: mudança de comportamento = v2); `app/api/jobs.py` salvo extensões aditivas cobertas por teste; ADR-0001…0024 (novas ADRs acrescentam, não reescrevem); `docs/addenda/v2.2/**`; `contracts/fibercore-v2.openapi.yaml` salvo adições; seed/demos existentes; `configs/modules.yaml` salvo acréscimo de módulo opcional.

## 7. Decisões / ADRs necessárias antes de código novo

| ADR | Assunto | Padrão recomendado (vale até decisão diferente) |
|---|---|---|
| D-1 (ADR-0025) | Integração SD-001: nomes, `diagnostic_jobs` vs `diagnostic_runs`, mapa de escopos, convenção de eventos | C-1…C-5 acima |
| D-2 (ADR-SD-001) | Estender workers existentes vs novo serviço | **estender** (`app/workers`), sem container novo |
| D-3 (ADR-SD-002) | Leitura de árvore de parâmetros do CPE | lista de caminhos permitida por perfil, redação no Edge, nada de PSK/senha; **só depois** de fechar o NBI |
| D-4 (ADR-SD-004) | Fronteira de aprovação | reutilizar `jobs`/`job_approvals`; proposta imutável com `proposal_hash` ligado à aprovação |
| D-5 (ADR-SD-003/005/006) | Servidor de teste/quotas; controller USP; provedor LLM + LGPD | adiados, cada um com gate próprio; não bloqueiam D1–D2 |
| D-6 | Quem tem root no host do GenieACS | pendente do usuário (já aberto desde o PR 37) |

## 8. Backlog ajustado (mapeado ao existente, sem renumerar)

| Onda do pacote | Mapeia para | Observação |
|---|---|---|
| D1 capacidades + coleta read-only | FC22-002 (extensão) + novo SD-D1 | começa por **contratos e mocks**; coleta real de WAN/Wi-Fi fica bloqueada por D-3 |
| D2 ciclo de vida assíncrono de diagnóstico | novo SD-D2 (`diagnostic_jobs`) | reaproveita outbox/NATS; **sem** escrita |
| D3 testes ativos | FC22-014 (catálogo de operações) | exige D-5 |
| D4 RCA + copiloto | FC22-006 (R-D001 pronta) + R-D002…D004 | R-D002…D004 dependem de dados; copiloto bloqueado por ADR-0015 |
| D5 UX | FC22-005/007 (extensão) + 1 lote Lovable | capturas reais |
| D6 propostas/aprovação | FC22-014/015 | sem driver de escrita |
| D7–D8 laboratório e canário | FC22-016 + autorização operacional separada | **fora do alcance até haver dispositivo de laboratório, firmware homologado e ordem humana** |

**PRs propostos (pequenos, na ordem):**
1. `SD-PR-00` — este relatório + ADR-0025 (docs apenas).
2. `SD-PR-01` — contratos e mocks: OpenAPI aditivo, schemas de evidência/saída, fixtures sintéticas, validação em CI; flags `smart_diagnostics_*` default **off**; módulo opcional no registry; **sem endpoint real, sem migração**.
3. `SD-PR-02` — extensão do `device_capabilities` (`parameter_paths`, TTL, `lab_evidence`) + CLI; Edge ainda não alimenta.
4. `SD-PR-03` — `diagnostic_jobs` + outbox + worker + evidências com frescor, **fonte única = o que já existe** (OLT/ONU/ERP/CPE identidade), sem testes ativos e sem escrita.
5. `SD-PR-04…` — conforme gates acima, cada um depois de sua ADR.

## 9. Riscos

1. Colisão de nomes (`diagnostic_runs`) quebraria testes e o contrato publicado → mitigada por C-1.
2. Ampliar a leitura do NBI sem redação vazaria PSK/PPPoE → D-3 e NBI fechado primeiro.
3. Duplicar approval/execução criaria dois caminhos de autorização → C-3.
4. Declarar "diagnóstico completo" sem WAN/Wi-Fi seria enganoso → a UI deve mostrar **cobertura** e `unsupported/not_configured`, nunca zero.
5. Driver de OLT ainda `identified`: nenhuma PON sai `complete` até a promoção a `observed`.

## 10. Testes e CI existentes a estender

`apps/api/tests/*` (pytest, TEST_ADMIN_DATABASE_URL + NATS), `scripts/e2e.sh` (Playwright + axe + capturas), `agents/edge` (`go vet`/`go test`), `tests/validate_kit.py|validate_help.py|validate_addendum_v22.py`, ruff. O `validate_bundle.py` do pacote valida o **pacote**, não o produto, e não foi executado.

## 11. Fora de escopo deste gate

Nenhuma escrita em equipamento, ACS, banco real, DNS ou produção foi feita ou autorizada por este relatório. Toda escrita real exige homologação por modelo/firmware e **autorização operacional separada**, conforme o pacote e as regras do projeto.
