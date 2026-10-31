# Roadmap executável (Claude + Codex + Lovable)

## Sprint 0: bootstrap, segurança e contratos — gate inicial

- [ ] Inventário repo, importar legados sem destruí-los, escrever ADRs 1–10.
- [ ] Compose válido, API `/livez` `/readyz` `/modules`, NATS/Postgres, log JSON, migrations.
- [ ] Auth real e tenants com RLS; testes `tenant A`/`tenant B`, endpoint com token real, secrets sem plaintext.
- [ ] Registry de módulos e feature flags; painel status de serviços baseado em dados reais.
- [ ] OpenAPI v2 lint, geração tipos TS/Python, CI lint/test/contract/secret scan.
- [ ] Memory/wiki/ADR+checkpoint obrigatório; Codex PASS.

## Sprint 1: Edge e coleta real (read-only)

- [ ] Edge Go outbound autenticado, configuração local allowlist, heartbeat, cache e replays.
- [ ] GenieACS NBI read-only: devices, projection, last inform, snapshots com staleness.
- [ ] Huawei MA5800 modelo/firmware conhecido fixture -> driver inventário real; testar desconexão sem false offline.
- [ ] ZTE segundo driver read-only em lab/fixture.
- [ ] Sem comandos automáticos de alteração/provisionamento.

## Sprint 2: produto inicial

- [ ] CSV e generic REST ERP, clientes/contratos e associação de evidências.
- [ ] Raio-X FTTH, página ONU 360, busca global e painel NOC.
- [ ] Correlação massiva PON, dedupe e supressão falha Edge.
- [ ] UX-01 a UX-05 com Lovable + testes e Codex.

## Sprint 3: workflows controlados e dual-stack

- [ ] Job state machine, preview, approval, signature, TTL, audit, lock por device/capability.
- [ ] Reboot CPE via GenieACS somente após lab; HTTP 202 tratado queued; pós-check.
- [ ] Interface TR-369, contrato unitário, simulador USP Controller/Agent e PoC OB-USPC (com critérios de segurança/HA/license).
- [ ] Dual-stack conflict tests, update agent canary e version/changelog.

## Sprint 4: comercial / módulos expansíveis

- [ ] SGP/IXC (ou ERP selecionado) mediante acesso real e fixtures redigidas.
- [ ] Driver certificação por firmware, novos templates, OLT read/write lab, provisioning wizard.
- [ ] USP controller em ambiente homologado e testes TR-181/USP, se viável; senão feature flag off.
- [ ] métricas SRE, SLO e hardening, teste restore/chaos, opção K3s se demandado.

## Sprint 5+: inteligência assistida

- [ ] Copiloto read-only com corpus técnico restrito, roteador provider, avaliações e observabilidade.
- [ ] Tool facade sugestão de operação -> humano aprova fora do LLM -> job controlado.
- [ ] Mapa CTO, expansão, relatórios, webhooks, custos por tenant, scale benchmark.

## Definição de pronto (DoD) para cada PR

1. API/schema versionados e testes unitários/contrato.
2. Autorização multitenant e audit de ações/dados onde aplicável.
3. Falha do módulo opcional isolada e estado degradado visível.
4. Edge/device test com fixtures saneadas, sem comandos não certificados.
5. Segurança: lint, dependency scan, secrets scan, threat model para writes.
6. Métricas, logs redigidos, health/ready, timeout, retry e DLQ quando aplicável.
7. Docs de módulo, wiki, ADR, changelog, contexto e limite conhecido atualizados.
8. Codex revisão `PASS` (BLOQUEAR mudanças críticas se `BLOCK`) e Lovable UX review em mudança visual.
9. Testes devem registrar resultado real ou `NOT_RUN` com explicação; nunca alegar sucesso sem execução.

## Ordem de paralelismo

Codex não revisa códigos ainda não finalizados; Lovable pode trabalhar telas usando mocks e contratos versionados em paralelo ao Edge. Claude deve concluir caminhos verticais antes de abrir mais serviços. Sem **merge autônomo de PR crítico** e sem writes em equipamentos sem aceite humano.

## Backlog adicional obrigatório — v2.1 (domínio e Help-by-construction)

**Sprint 0:** registrar ADR do hostname, manifesto canônico e fluxos Caddy/Ingress; manter proxy público desabilitado enquanto auth/RLS estiverem incompletos; gerar `configs/ui/design-tokens.json` e definir contrato `/ajuda`, `/api/v1`.

**Sprint 1 / primeira UI:** construir AppShell e biblioteca de componentes conforme design system; documentação/central de ajuda com roteamento contextual e busca por título; criar Playwright com seed sintética e caso E2E para screenshots; sem dados falsos em produção.

**Cada sprint visual:** capturar desktop 1440×900 e mobile 390×844, atualizar artigo respectivo + índice + last_verified e revê-los no Codex. Mudança de UI exige regenerar captura (do sistema funcionando, não do Lovable). Registrar status `draft` antes disso.

**Gate de publicação:** DNS e TLS em `fibercore.devops.k3gsolutions.com.br`, apenas 443/80 no proxy, Same-Origin API, testes de autenticação isolada e controle de acesso, CSP/cookies, rollback, monitoramento e checklist `infra/deploy/PRODUCTION_CHECKLIST.md`.

## Adendo v2.1 — backlog adicional (domínio, design system, ajuda por construção)

Inventário em 2026-10-28: backend/Edge/jobs/ERP/NOC prontos e testados; **nenhuma tela existe**. Tarefas existentes preservadas; as abaixo são novas.

- [x] ADR-0012 domínio/proxy/`/api/v1` · ADR-0013 design system+ajuda · ADR-0014 sessão BFF (Proposed).
- [x] OpenAPI `servers: /api/v1`; proxy Caddy (profile `public`) com E2E `scripts/test-proxy.sh`; `validate_help.py` no gate.
- [x] W1 `apps/web` scaffold Next.js/TS/Tailwind + tokens + AppShell + tema claro/escuro (proposta Lovable → integração).
- [x] W2 BFF de sessão (login/logout/workspace) + testes de segurança.
- [x] W3 Pipeline Playwright (`apps/web/e2e/help-screenshots.spec.ts`) + fixtures sintéticas + `HelpContextLink`.
- [x] W4 Central de Ajuda `/ajuda` (busca, deep link, só `docs/help`).
- [x] W5 Tela Rede: OLT/PON/ONU (frescor, `support_level`) + How-to `rede/consultar-onu`.
- [x] W6 Tela NOC: fila de incidentes (silêncio de Edge ≠ offline) + How-to `noc/acompanhar-incidente`.
- [x] W7 Tela Administração/Módulos + How-to `administracao/saude-modulos`.
- [x] W8 Telas Assinantes (importar CSV, revisar vínculos) e Operações (jobs; escrita bloqueada visível) com How-to (importar CSV, revisar associações) e Jobs (preview/aprovação; escrita bloqueada visível) com How-to.
- [ ] W9 Hardening de publicação: MFA/refresh/rate-limit, CSP, HSTS (só após TLS real), DNS/TLS/ACME reais, Codex PASS.

## v2.2 — Adendo de benchmark ACS/FTTH (integrado em 2026-10-29)

Fonte: `docs/addenda/v2.2/` (pacote intacto). Análise: `docs/addenda/v2.2/GAP_ANALYSIS.md`; contrato reconciliado: `docs/addenda/v2.2/contracts/fibercore-v2.2-reconciled.openapi.yaml`; ADRs 0019–0023. **Marcar item só com código + teste + (se tela) captura real + how-to + parecer Codex.**

| ID | Pri | Estado (verificado no repo) | Sprint | Depende de |
|---|---|---|---|---|
| FC22-001 | P0 | [x] análise de GAP/conflitos/ADRs (PR 34) | S0 | — |
| FC22-002 | P0 | [~] **fatia mínima implementada (PR 35)**: tabela `device_capabilities` (RLS, leitura-only p/ a app), `GET /cpes/{cpeId}/capabilities` e `/olts/{oltId}/capabilities`, CLI `capability-set` com evidência, bloco na ONU 360. **Faltam**: cobertura TR-369/Wi-Fi, gate por perfil nos jobs, Edge alimentando o registro | S0/S1 | 001 |
| FC22-003 | P0 | [~] envelope `provenance{source,observed_at,quality}` na ONU 360 (PR 36); falta nas demais respostas/telas | S1 | 001 |
| FC22-004 | P0 | [x] PR 37: `/v1/customers/{id}/context` + vínculo ONU↔CPE por evidência com confirmação humana (flags `onu_cpe_links`/`customer_context`, desligadas por padrão); falta: regras de vínculo além de serial igual | S1 | 002, 003 |
| FC22-005 | P0 | [x] PR 38: `/assinantes/[id]` (entrada por cliente, abas Conexão/Óptica/Roteador/Cliente/Ações só com dado, flag `subscriber_360`); falta: busca por cliente/contrato no ⌘K, Wi-Fi e Histórico (sem fonte homologada) | S1 | 004 |
| FC22-006 | P0 | [x] PR 39: R-D001 v1 extraída (função pura; o correlator a usa sem mudar comportamento), registro versionado, `diagnostic_runs` append-only, `POST /diagnostics/runs` somente-leitura + replay (flag `diagnostic_engine`). Faltam: R-D002..004 (dependem de dados Wi-Fi/WAN/sessão ACS ainda não coletados), UI (FC22-007) | S2 | 002–004 |
| FC22-007 | P0 | [x] PR 40: `/assinantes/diagnostico/[id]` (5 passos, Confirmado/Hipótese/Indisponível, resumo para ticket; só R-D001; sem timeline) | S2 | 006 |
| FC22-008 | P0 | [x] validado contra AC-004/009 (`docs/addenda/v2.2/AC_VALIDATION_FC22-008.md`; +1 teste); lacunas declaradas: R-D003 como regra, R-D004, impacto (FC22-009) | S2 | — |
| FC22-009 | P0 | [x] PR 42: `/noc` com 4 KPIs, fila priorizada (ordem documentada), impacto (clientes distintos por associações aprovadas, Edge silencioso fora do impacto atual) e painel lateral; falta: ack pela UI | S2 | 008, 004 |
| FC22-010 | P1 | [ ] falta (sem CTO/POP no modelo) | S3 | 003 |
| FC22-011 | P1 | [ ] **bloqueado por dados** (ADR-0022) | S3 | 002, 003 |
| FC22-012 | P1 | [ ] **bloqueado** (telemetria Wi-Fi/WAN não coletada; NBI aberto) | S3 | 002, ADR-0022 |
| FC22-013 | P1 | [ ] falta | S3 | 011/012 |
| FC22-014 | P1 | [ ] parcial: motor de jobs; falta catálogo/dry-run com diff | S4 | 002 |
| FC22-015 | P1 | [ ] parcial: idempotência/CAS; sem lock por dispositivo; USP ausente | S4 | USP |
| FC22-016 | P1 | [ ] parcial: módulos/versões; falta changelog/canary | S4 | — |
| FC22-017 | P1 | [x] prática vigente (gate por PR de tela) | contínuo | — |
| FC22-018 | P2 | [ ] adiado (ADR-0015) | pós-S4 | 004, 006 |
| (DoD) flags por tenant | — | [x] PR 36: `tenant_features`, `feature-set`, `/v1/tenant/features`, kill switch do registro | S1 | — |



## Feature Pack SD-001 (Smart Diagnostics & Remediation) — ligado ao backlog, sem renumerar (2026-10-29)
- Gate B0 entregue: `docs/feature-packs/SD-001/BASELINE_COMPATIBILITY_REPORT.md` + ADR-0025 (Accepted em 2026-10-29). P0/P1/P2 e FC22-001…009 permanecem como estão.
- Ordem proposta: SD-PR-01 contratos+mocks+flags off → SD-PR-02 `device_capabilities` (parameter_paths/TTL) → SD-PR-03 `diagnostic_jobs` read-only → (após ADRs) coleta WAN/Wi-Fi, testes ativos, propostas/aprovação (sobre o gate de jobs), homologação em laboratório.
- Bloqueios: ADR-SD-002 (árvore de parâmetros + NBI fechado), ADR-0015/ADR-SD-006 (copiloto), ADR-SD-003 (testes ativos), ADR-SD-005 (USP). Escrita real: homologação + autorização operacional separada.

## v2.4 — ONT Configuration Manager (FC24-*), incorporado SEM reiniciar a sprint (ADR-0034, `docs/addenda/v2.4/`)
| ID | Prio | Estado | Dependência |
|---|---|---|---|
| FC24-00 | P0 | [x] GAP (`docs/addenda/v2.4/GAP_ANALYSIS.md`) + ADR-0034 + backlog | — |
| FC24-01 | P0 | [x] leitura: catálogo fechado, ingestão `cpe-config`, `configuration` / `capabilities` / `form-schema`, perfis sintéticos; **só mocks, nada lido de ONT real** | FC22-002 |
| FC24-02 | P0 | [ ] sidebar direito recolhível (miniatura, abas, formulários só leitura) + ajuda `/ajuda/ont/*` com capturas reais | 01 |
| FC24-03 | P0 | [ ] preview/policy/jobs por capacidade (`If-Match`, diff redigido, risco, aprovação) com mocks | 01, jobs |
| FC24-04 | P0 | [ ] adaptador GenieACS seguro no Edge (leitura ampla; escrita só em laboratório autorizado; SSID/enable primeiro numa combinação) | 03 |
| FC24-05 | P1 | [ ] Wi-Fi abrangente (senha write-only por `secret_ref`, canal, largura, potência certificada) | 04 |
| FC24-06 | P1 | [ ] LAN e WAN (R3: OOB, janela, dupla aprovação) | 04 |
| FC24-07 | P2 | [ ] adaptador USP (Controller real homologado; lock comum) | 04 |
| FC24-08 | P1 | [ ] métricas, rollback/reconciliação, gate humano | 05 |
