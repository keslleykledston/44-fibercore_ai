# Changelog

## [0.0.0-spec] - 2026-10-27

- PRD e arquitetura dual TR-069/TR-369.
- Kit inicial com inventário de módulos, catálogo seed, contratos, orquestração e comandos de desenvolvimento.
- Nenhuma integração real com dispositivos habilitada.

## Unreleased — Sprint 0 PR 1
- Kit v2 importado; starter movido para `apps/api`.
- Migração 0001: tenants, users_global, tenant_memberships, service_accounts, audit_log, events_outbox + RLS forçada + role `fibercore_app`.
- Auth JWT/Argon2id, RBAC, `X-Workspace-ID`, service accounts, CLI de provisionamento.
- Registry de módulos com probes reais; Compose com `migrate` one-shot.

## Unreleased — Sprint 1 PR 5
- Migration 0005 (olts, pon_ports, onus, cpes, bindings; RLS; sem DELETE para runtime).
- Ingestão `POST /v1/edge/{olt,cpe}-snapshots` (token ligado a um edge; anti-hijack; fora de ordem ignorado; `certified` só no servidor) e leituras `/v1/{olts,onus,cpes}` com `freshness`.
- OpenAPI 0.3.0-draft: schemas Olt/Onu/Cpe reescritos para o implementado (breaking vs 0.2 draft; sem consumidores ainda).

## Unreleased — Sprint 2 PR 8
- Migration 0006: customers (documento só como HMAC+last4), associations (1 aprovada por ONU), import_batches.
- `POST /v1/erp/import-csv`, `/v1/customers`, `/v1/associations` (+approve/reject, auditados, evento no outbox). OpenAPI 0.4.0-draft.

## Unreleased — Sprint 2 PR 9
- Migration 0007 `incidents`; correlação de queda em massa por PON na ingestão (histerese, dedupe, evidência só com contagens); `/v1/incidents`, `/v1/incidents/{id}/ack`; eventos `incident.opened/resolved`. OpenAPI 0.5.0-draft.

## Unreleased — Sprint 3 PR 10
- Migration 0008 (jobs, job_approvals); `/v1/jobs/*`, `/v1/edge/jobs/next|result`; assinatura Ed25519; Edge verifica assinatura/binding/expiração/nonce e só executa collect/refresh. OpenAPI 0.6.0-draft.

## Unreleased — Adendo v2.1 (PR 11)
- Kit v2.1 (design system, help center contract, Caddy example, validate_help) importado; OpenAPI 0.7.0-draft (`/api/v1`); profile Compose `public` com Caddy; `scripts/test-proxy.sh`; lockfile corrigido (cryptography) e atualizado para versão sem advisories; CI valida import da imagem.

## Unreleased — Hardening 13
- Migration 0010 `login_attempts`; lockout 5 falhas/15 min em `/v1/auth/token` e `/v1/auth/service-token` (429 + Retry-After); BFF mostra mensagem específica.

## Unreleased — Correlação por quedas recentes (ADR-0018)
- Migration 0012 (`onus.last_online_at/down_since`, `incident_onus`); `pon_mass_outage` passa a medir ONUs que CAÍRAM na janela de 6 h (só em snapshot fresco pelo relógio do servidor) (crônicas fora do cálculo), incidente guarda as ONUs que cobre e resolve quando elas voltam. Motivo: 37% das ONTs de uma OLT real estavam offline crônicas e a regra antiga abriria incidente falso permanente em 2/32 PONs.

## Unreleased — Segurança da conta / MFA (PR 27)
- Tela `/conta/seguranca` (ativar/desativar MFA, QR, códigos de recuperação mostrados uma vez) e política `MFA_REQUIRED_ROLES` (403 `mfa_enrolment_required`, sem auto-downgrade, boot falha com papel desconhecido). ADR-0017 (adendo).
- Correção: `tenant_conn` confirma a transação ANTES de enviar a resposta (`scope="function"`; fastapi >= 0.121) — corrigia um `job not found` intermitente logo após o preview.
- Correção: ativação do MFA serializada (`FOR UPDATE`) e enroll com upsert condicional (não sobrescreve MFA ativo); 409 para quem perde a corrida. Codex: 4 rodadas, approve final (pareceres em `docs/wiki/reviews/raw/27-*`).

## Unreleased — ONU 360 (PR 28)
- `GET /v1/onus/{id}` (estado, OLT/PON com idade do dado, incidente com `incidents:read`) e `GET /v1/onus/{id}/customer` (dado pessoal: `customers:read`, auditado). Página `/rede/onu/[id]`, painel lateral `EntityDetailDrawer` (dialog) na tabela de Rede, how-to com capturas. Codex: 4 rodadas, approve.

## Unreleased — Edge × GenieACS NBI (PR 30)
- Coletor GenieACS descarta identidades provisórias `DISCOVERYSERVICE` (37 de 43 dispositivos no servidor real) e reporta só contagens (`no_serial`, `placeholder_identity`). Teste com fixture sintética da estrutura real; mutação verificada.
- Identidade de CPE como REIVINDICAÇÃO do dispositivo: serial canônico (trim + maiúsculas) no Edge e na API, migration 0013 (CHECK de forma canônica + único `(tenant, cpe, connector, protocol)`; recusa dados colidentes com diagnóstico), ingestão que IGNORA e conta (`conflicts`) reivindicações conflitantes sem derrubar o lote, travas advisory em ordem por chave de serial e de binding. Contrato OpenAPI (`CpeSnapshotAck`). Codex: 11 rodadas, approve (4 alegações contestadas com medição/teste; pareceres em `docs/wiki/reviews/raw/30-*`).

## Unreleased — Redefinição de MFA por administrador (PR 31)
- `GET /v1/members` e `POST /v1/members/{id}/mfa/reset` (senha + segundo fator do administrador, guarda de conta multi-workspace, auditoria, sessões revogadas, fail closed). Tela Administração › Membros com abas, how-to com captura, E2E do fluxo completo. ADR-0017 (adendo).
- Migration 0014 `users_global.tokens_valid_after`: revogação verificável de access tokens já emitidos (reset de MFA encerra sessões na hora); `iat` do JWT passa a ser fracionário.

## Unreleased — Backup agendado
- `scripts/backup-scheduled.sh` (cron diário 03:15) reaproveita `backup.sh`/`restore-verify.sh` (agora com `COMPOSE_PROJECT` p/ a stack `fibercore-prod`), verifica cada dump restaurando num banco descartável e mantém os 14 mais recentes.

## Unreleased — Regeneração de códigos de recuperação (PR 33)
- `POST /v1/auth/mfa/recovery-codes` (senha + segundo fator; troca o conjunto inteiro na mesma transação, serializado com disable/reset) e botão em Conta › Segurança da conta. How-to e contrato atualizados.

## Unreleased — Adendo v2.2 (PR 34, somente planejamento)
- Pacote do adendo copiado para `docs/addenda/v2.2/` sem alterar nada existente; `GAP_ANALYSIS.md` (matriz de gaps + 18 conflitos + plano), `RECONCILED_API.md` + OpenAPI reconciliado, `SCREEN_COMPONENT_MAP.md`, `TEST_DESIGN.md`; ADR-0019…0023; backlog FC22 integrado ao `ROADMAP_BACKLOG.md`; `tests/validate_addendum_v22.py` (no `make validate`). **Nenhuma funcionalidade v2.2 foi implementada neste PR.**

## Unreleased — Capability Registry, fatia mínima (PR 35, FC22-002)
- Migration 0015 `device_capabilities` (por tenant, RLS forçada, CHECKs; `observed/certified` exigem evidência+data; app só lê), `GET /cpes/{cpeId}/capabilities` (documentada no contrato sem handler) e `GET /olts/{oltId}/capabilities`, catálogo = operações reais do motor de jobs, CLI `capability-set` (evidência obrigatória, evento `device.capabilities.changed`), bloco "Capacidades" no card Ações da ONU 360 + how-to e capturas. Registro vazio ⇒ tudo `Desconhecida/Identificado`; o registro NUNCA libera escrita (o gate é o do motor de jobs).
- **Não feito (declarado)**: flag por tenant (DoD parcial), gate de jobs ligado ao registro, Edge alimentando o registro, capacidades TR-369/Wi-Fi.

## Unreleased — Flags por tenant + envelope de proveniência (PR 36, FC22-003/ADR-0023)
- Migration 0016 `tenant_features`; `app/core/features.py` (catálogo+padrões no código); `GET /v1/tenant/features`; CLI `feature-set`; `403 feature_disabled` (kill switch do registro de capacidades). ONU 360: `provenance{state,olt,pon}` + `SourceChip`. ADR-0020/0021/0023 → Accepted (0021 aprovado pelo responsável em 2026-10-29).

## Unreleased — Vínculo ONU↔CPE por evidência + Customer Context (PR 37, FC22-004/ADR-0021)
- Migration 0017 `onu_cpe_links` (RLS forçada; `suggested|confirmed|rejected`, confiança, evidência; `CHECK` sugestão ⇒ sem revisor; índices únicos parciais: um confirmado por ONU e por CPE; app só `INSERT` + `UPDATE(status, reviewed_by, reviewed_at)`).
- `POST /v1/onu-cpe-links/suggest` (serial igual ⇒ sugestão 0.50, 0.20 se ambíguo; idempotente; nunca confirma), `GET /v1/onu-cpe-links`, `POST …/{id}/confirm|reject` (pessoa; auditado + outbox; 409 em ambíguo/já revisado/duplicado). `GET /v1/customers/{id}/context` (read-only, `customers:read`, auditado, flag `customer_context`): só ONUs de associação aprovada, CPE só com vínculo confirmado, proveniência por bloco, status `unknown > stale > partial > complete`, incidente só com `incidents:read`.
- ONU 360: bloco `cpe` + card "Roteador (CPE)" com confirmar/rejeitar (BFF `/bff/onu-cpe-links`). Seed demo liga as flags no tenant demo. Flags continuam **desligadas por padrão** em produção.
- TTL do dado de ERP = 7 dias (`ERP_FRESH_FOR`), **aprovado pelo responsável em 2026-10-29**; acima disso o contexto vira `stale`.
- **Não feito (declarado):** busca por cliente/contrato na UI (FC22-005), regras de vínculo além de `serial_equal`, desfazer um vínculo confirmado.

## Unreleased — Visão 360 do assinante (PR 38, FC22-005)
- `/assinantes/[id]` (Next, servidor): estado geral explicado (Completo/Parcial/Defasado/Desconhecido), seletor de ONU, abas por query (`?aba=`) só com dado — Conexão (conexão + roteador + incidente), Óptica, Roteador (CPE), Cliente, Ações (sempre bloqueadas). Lista "Clientes · visão 360" em Assinantes. Tudo atrás das flags `subscriber_360` **e** `customer_context` (desligadas por padrão; faltando qualquer uma a rota é 404 e a lista não aparece; o bloco do roteador precisa ainda de `onu_cpe_links`). Consome `GET /v1/customers/{id}/context` (sem API nova).
- Referência visual do Lovable (um lote); how-to `assinantes/visao-360` + capturas reais 1440×900/390×844; seed demo liga a flag.
- **Não feito (declarado):** busca por cliente/contrato no ⌘K, Wi-Fi e Histórico (sem fonte homologada), caminho "flag desligada" não coberto por E2E (só 404 por construção + flags testadas no backend).
## Unreleased — Motor de regras de diagnóstico, R-D001 v1 (PR 39, FC22-006/ADR-0024)
- `app/core/diagnostics.py`: regra pura e versionada; R-D001 v1 extraída do correlator **sem mudar comportamento** (o `noc.py` a chama para decidir abrir; teste de propriedade com 2000 casos contra a fórmula original). Migration 0018 `diagnostic_runs` (append-only, RLS forçada). `GET /diagnostics/rules`, `POST /diagnostics/runs` (somente leitura, não abre incidente), `GET /diagnostics/runs/{id}` com `reproducible`. Flag `diagnostic_engine` (desligada por padrão), permissão `diagnostics:run`.
- **Não feito (declarado):** R-D002..004 (sem dados de Wi-Fi/WAN/sessão ACS), UI de troubleshooting guiado (FC22-007), completude de PON persistida.
## Unreleased — Diagnóstico guiado (PR 40, FC22-007)
- `/assinantes/diagnostico/[id]` (Next, servidor): 5 passos (cliente, ONU, estado/óptica, padrão R-D001, roteador) com rótulo Confirmado/Hipótese/Indisponível, painel de evidências com fonte/idade, ação de leitura por passo, conclusão que só existe depois de executar, "Gerar resumo para ticket" sem alterar a rede. BFF `/bff/diagnostics/run/[customer]/[onu]` executa a regra (somente leitura) e volta com o resultado; a execução só vale para a ONU da tela. Atalho "Diagnóstico guiado" na Visão 360. Exige as flags `subscriber_360`, `customer_context` e `diagnostic_engine` (fora: 404).
- API: `POST /v1/diagnostics/runs` aceita `onu_id` (PON resolvida no servidor; exclusivo com `olt_id`/`pon_id`).
- **Não feito (declarado):** R-D002..004 (sem dados), conclusão com Wi-Fi/WAN, histórico/timeline (FC22-007 pede EvidenceTimeline: sem fonte homologada).
## Unreleased — NOC Command Center (PR 42, FC22-009)
- API: `GET /v1/incidents` ganhou `impact` por incidente (clientes distintos via associações APROVADAS; sem `customers:read` = `hidden`, nunca 0; sem membros = desconhecido), `summary` (4 números sobre TODOS os abertos; clientes afetados não inclui Edge silencioso) e `order=priority` (ordem documentada, sem score; o padrão `recent` não mudou); `GET /v1/incidents/{id}` para o painel (evidências, impacto, até 50 ONUs-membro, sem nomes de clientes).
- UI `/noc`: 4 KPIs, filtro "só não reconhecidos", fila na ordem do servidor, impacto com fonte, incidente em painel lateral (foco/Esc) via BFF `GET /bff/incidents/[id]`. How-to atualizado, capturas reais.
- **Não feito (declarado):** reconhecer incidente pela UI (ack existe na API), correlação com dados de Edge além do silêncio, R-D003 como regra.

## Unreleased — PR 43 (Edge → OLT, ritmo seguro)
- Edge: a coleta de OLT (SSH/CLI e SNMP) passa por UM guard por equipamento físico: uma coleta por vez, intervalo mínimo (`collect_seconds`, padrão 15 min no CLI), resfriamento após falha (`cooldown_seconds`, padrão 15 min CLI / 5 min SNMP).
- O estado do guard (última tentativa + resfriamento) é gravado em `olt-guard.json` (0600, atômico) ANTES de qualquer E/S e sobrevive a restart; falha ao gravar = não toca na OLT; arquivo corrompido (inclusive `null`) = assume que a OLT acabou de ser tocada; timestamps >24 h à frente são normalizados e persistidos.
- Instância única por diretório de estado (`edge.lock`, flock). Chave do guard = host físico (`config.DeviceKey`), independente de transporte/porta; a config recusa duas entradas para o mesmo equipamento e exige IP literal no endereço de OLT por CLI.

## Unreleased — PR 44 (Edge → OLT, observabilidade)
- Edge: cada tentativa que chega à OLT registra `olt collected`/`olt collection failed` com duração (nunca saída do equipamento); o orçamento de tempo vira proporcional às PONs (1 min + 15 s/PON, entre 5 e 9 min) e cobre também o login.

## Unreleased — PR 45 (itens pequenos do v2.2)
- NOC: **Reconhecer incidente** no painel lateral (BFF `POST /bff/incidents/{id}/ack`; só registra a ciência, auditada; 403/409 tratados).
- Busca global (⌘K): clientes por nome a partir de 3 letras (BFF `GET /bff/search/customers`, só id e nome; a API audita o acesso).

## Unreleased — PR 46 (SD-001 gate B0, só documentação)
- `docs/feature-packs/SD-001/`: relatório de compatibilidade com a base v2.2, README do pacote; ADR-0025 (Proposed); ligação ao backlog sem renumerar. Nenhum código, contrato, migração ou versão alterado.

## Unreleased — PR 47 (SD-PR-01: contratos e mocks do SD-001, flags desligadas)
- ADR-0025 aceito pelo Tech Lead (2026-10-29). `contracts/sd001/`: schemas de evidência e de saída consultiva do copiloto, sobreposição OpenAPI **proposta** (`diagnostic_jobs`, propostas, aprovação, execução) e eventos no formato do outbox; fixtures sintéticas em `tests/fixtures/sd001/`.
- Flags por provedor `smart_diagnostics_jobs|active_tests|remediation|copilot`, todas desligadas (`features.py`). Nenhum endpoint, migração, tabela, evento emitido ou mudança no contrato canônico; `/devices/{id}/capabilities` do pacote não foi criado (já existe `/cpes/{id}/capabilities`).

## Unreleased — PR 48 (SD-PR-02: leitor passivo de parâmetros do CPE, ADR-SD-002)
- Edge: `nbi.CachedParams` lê, por GET, folhas exatas de uma lista fechada (WAN/enlace, uptime, rádio Wi-Fi habilitado/canal) do que o GenieACS já tem em cache, com validação de tipo e descarte do que não é esperado. Não é usado pelo coletor: nada novo vai à nuvem, sem endpoint nem migração.
- ADR-SD-002 (Proposed): evidência da LAB mostra que o cache só tem dados do Inform (sem WAN/Wi-Fi); a leitura ativa (`getParameterValues`) ficou separada e depende de autorização explícita. Estados novos no contrato de evidência.

## Unreleased — PR 49 (catálogo de consultas somente leitura da OLT, ADR-0026)
- Edge: `olt.Queries`/`HuaweiR015.RunQuery` — 25 consultas `display` tipadas (global, slot, PON, ONU), parâmetros inteiros limitados, renderização no Edge, padrão estrito e proibição de verbos de escrita. Só as 4 já executadas na OLT real são aceitas por padrão; as demais exigem habilitação local para captura supervisionada.
- `docs/operations/OLT_QUERY_CATALOG.md` (mapa runbook→ID e processo de promoção) e ADR-0026 (Proposed). Inerte: nenhum fluxo chama `RunQuery`, sem endpoint/job/migração.

## Unreleased — PR 50 (leitura ativa de parâmetros do CPE, ADR-SD-002 item 4)
- Edge: `nbi.RefreshParams` (tarefa `getParameterValues` por grupo, só nomes da lista fechada, detecção de modelo de dados, limpeza de tarefas pendentes) e `RefreshGuard` (1 por dispositivo/10 min, 20/h, persistido antes de pedir). Config `refresh_tasks` (padrão **desligado**; exige `nbi_url` + `jobs_enabled`).
- Nuvem: o despacho de `refresh` de um CPE assina `target_ref` (id TR-069 do binding) no envelope; contrato `job-envelope` ganhou o campo opcional. `collect` e CPE sem binding seguem como antes.
- ADR-SD-002 → Accepted (autorização do responsável em 2026-10-29).

## Unreleased — PR 51 (reconciliação de tarefas do refresh ativo)
- Edge: depois de um POST ambíguo, de uma tarefa em fila/falha ou de id inválido, `RefreshParams` lista as tarefas do dispositivo, apaga só as que a própria chamada criou (mesmo nome e mesmos parâmetros, carimbo recente) e confirma por nova listagem. Motivo: no ensaio real o ACS criou a tarefa e fechou a conexão (EOF).

## Unreleased — PR 52 (conexões WAN de instâncias 1..4 no refresh ativo)
- Edge: o refresh lê PPP e IP (instância 1) de `WANConnectionDevice` 1..4 (a EG8145V5 real tinha a conexão PPP na instância 3); 11 tarefas por refresh em TR-098, `maxGroups` 12, conjunto exato fixado por teste. Freio: `nbi.RefreshHold` segura o dispositivo 24 h após qualquer refresh com fault.
- Medição real na LAB (ONT de bancada): `completed=11 faulted=0 readable_metrics=7`, 0 faults novos e 0 tarefas residuais no ACS. ADR-SD-002 atualizado (validade da faixa, carga, freio).

## Unreleased — PR 53 (`cpe_state`: estado WAN/Wi-Fi do CPE até a nuvem)
- Migração 0019 `cpe_state` (RLS forçada, CHECKs de métrica/escopo/tipo). `POST /v1/edge/cpe-state` (Edge → nuvem) e `GET /v1/cpes/{id}/state`; contrato OpenAPI atualizado.
- Edge: o coletor do GenieACS envia `cpe_state` depois do inventário (só dispositivos do inventário; falha de leitura não derruba o inventário); gateway ganhou o endpoint.

## Unreleased — PR 54 (R-D002 v1: WAN do CPE, ADR-0027)
- Regra pura `R-D002` v1 sobre o `cpe_state` (frescor POR LEITURA; sem leitura ou leitura antiga que possa esconder uma conexão estabelecida = `unknown`; todas as conexões recentes e não estabelecidas = hipótese `inferred` com confirmação humana; o enlace só é Up/Down se todas as leituras são recentes e concordam; a ONU só dá contexto observado). `POST /diagnostics/runs` aceita `cpe_id`/`onu_id` para regras de CPE, somente leitura, mesma flag.

## Unreleased — PR 55 (SD-PR-03: diagnostic_jobs passivos, ADR-0028)
- Migração 0020 `diagnostic_jobs` (imutável, RLS forçada, idempotência). `POST /v1/diagnostics/jobs` e `GET /v1/diagnostics/jobs/{id}` (flags `smart_diagnostics_jobs` + `diagnostic_engine`, desligadas por padrão): evidências do que já está retido (ONU e `cpe_state`), regras R-D001/R-D002 com entradas gravadas e replay, achados que citam evidência; dado antigo/ausente = `insufficient_evidence`. Operações movidas do overlay SD-001 para o contrato canônico.
- Correção de teste: a verificação "nenhuma rota do SD-001 existe" lia `app.routes` (neste FastAPI só mostra `/openapi.json`) e era vazia; agora usa o esquema OpenAPI gerado pela aplicação.

## Unreleased — ADR-0029 (Proposed): canal de execução das consultas da OLT
- Só documento (Codex approve em 5 rodadas): operação `olt_query` R0 sobre o catálogo do ADR-0026, intenção assinada estrita por consulta, sessão única do guard, estados duráveis com no máximo uma execução, instância única como pré-condição bloqueante, fencing e arrendamento em memória. Nenhum código, nenhuma execução na OLT; aguarda o aceite do responsável.

## Unreleased — ADR-0030 (Proposed): homologação em bancada
- Só documento (Codex approve em 6 rodadas): escopo restrito à ONT de bancada em três lugares independentes, conferência física antes de cada manobra, catálogo de manobras (H2 reboot, H3 SSID, H4 ONU na OLT), gate com seis condições (inclui autorização prévia de uso único), claim durável, trava de escrita e evidência verificável. Nenhum código, nenhuma escrita em equipamento.

## Unreleased — PR 56 (ADR-0030, H0 lado nuvem): gate de bancada
- Migração 0021: `bench_targets` e `bench_authorizations` (escritas só pelo owner CLI; o app lê, trava o alvo e consome a autorização) e `jobs.authorization_id`/`owner_epoch`. Flag `bench_writes` (desligada). `app/core/bench.py`: catálogo de manobras (`reboot_cpe` sem parâmetros), gate de seis condições fail-closed (flag, alvo de bancada destravado e Edge registrado, capacidade `observed` do perfil exato, parâmetros do catálogo, autorização PRÉVIA de uso único), `HOMOLOGATED_WRITES` continua vazio e bloqueia todo o resto.
- Jobs: aprovação mínima de 1 pessoa distinta; a autorização é consumida de forma atômica na aprovação; envelope assinado leva `authorization_id`, `authorization_ends_at`, `owner_epoch` e `target_ref`, com validade nunca maior que a janela; o despacho reverifica tudo; qualquer resultado que não seja sucesso confirmado, ou job despachado e nunca reportado, trava o alvo (`bench-unlock`).
- Owner CLI: `bench-target-add/remove`, `bench-authorize`, `bench-unlock`; `capability-set` de operação de bancada exige arquivo de evidência com todos os campos e nunca concede `certified`. Modelo em `docs/wiki/bench/TEMPLATE.md`.
- `bench.EDGE_SUPPORT = False`: o servidor, o owner CLI e os testes recusam habilitar, autorizar e despachar até o PR do Edge; envelope de bancada vive no máximo 2 min; `owner_epoch` nunca volta (tabela `bench_target_epochs`); nenhum envelope sai sem a transição DISPATCHED confirmada (Codex approve em 3 rodadas).
- Ainda NÃO feito (PR 57): lado Edge (configuração `bench`, conferência do CPE no ACS, claim durável, arrendamento) e a execução real da H2. Nenhuma escrita em equipamento.


## Unreleased — PR 57 (ADR-0030, lado Edge do gate de bancada + código do H2)
- Edge: `internal/bench` (runner), `jobs/claims.go` (claim durável), `jobs/lease.go` (lease assinada, só em memória), `nbi/bench.go` (identidade + única tarefa `reboot`), `BenchWriteOps` separado do `ReadOnlyOps`, seção `bench` na configuração, guard de ritmo próprio, execução fora do laço de poll.
- Nuvem: `X-Bench-Lease` em toda resposta de `jobs/next`; `bench.EDGE_SUPPORT = True` (precondição, não abertura: flag, alvo, registro e autorização prévia continuam exigidos).
- Runbook do responsável: `docs/wiki/bench/RUNBOOK-H2-REBOOT.md`. Emenda proposta no ADR-0030 (primeira execução).

## Unreleased — PR 58 (ADR-0030, primeira execução)
- Migração 0022: `bench_authorizations.first_run`. `bench-authorize --first-run`. O gate aceita, SÓ enquanto não há `observed`/`certified` completo, uma autorização `first_run` + entrada `supported`/`identified` completa do perfil exato; rechecado no despacho.

## Unreleased — PR 59 (Edge: firmware do CPE no snapshot)
- O coletor do GenieACS passa a ler `DeviceInfo.SoftwareVersion` do cache do ACS (GET, sem tarefa) e a enviá-lo como `firmware` no snapshot do CPE (identificador simples ou vazio). Necessário para o registro de capacidades casar firmware exato (ADR-0030).

## Unreleased — PR 61 (ADR-0030 H3 `set_wifi_ssid`, código; nenhuma manobra executada)
- Nuvem: `set_wifi_ssid` no catálogo de bancada com parâmetro `ssid` (formato fixo), `params` assinado no envelope, `bench-authorize --ssid`, hash da autorização ligado ao SSID.
- Edge: `nbi/bench_ssid.go` (lê original, grava registro de restauração, muda uma vez, lê de volta, restaura e lê de volta), `RestoreFile`, runner com resultado por etapa.

## Unreleased — PR 62 (Edge: ritmo da bancada configurável, motivo local da recusa)
- `bench.min_interval_seconds` (0 = 30 min; mínimo 60) e `bench.max_per_hour` (0 = 2; máximo 20) na configuração do Edge, a pedido do responsável durante a homologação; o padrão do produto continua 30 min. O Edge passa a logar localmente o motivo exato de cada recusa/falha de manobra (nada disso viaja à nuvem).

## Unreleased — PR 63 (ADR-0030 H4 `onu_reset` / `onu_deactivate`, código; nenhuma manobra executada)
- Nuvem: operações `onu_reset`/`onu_deactivate` (alvo = CPE de bancada, sem parâmetros), perfil de registro = o da OLT alcançada pelo vínculo ONU↔CPE confirmado, CLI aceita os pares `olt`.
- Edge: `internal/olt/bench.go` (lista fechada e exata de comandos, identidade na mesma sessão, reativação sempre, recuperação), `collector.OLT.Exclusive` (mesmo guard das coletas), seção `bench.olt`, execução do runner com ritmo e autorização gastos só depois da identidade.

## Unreleased — PR 67 (Edge: cooldown pós-falha da bancada configurável)
- `bench.olt.cooldown_seconds` (0 = 900; 60..900): quanto tempo a OLT fica em paz depois de uma sessão de manobra que FALHOU. O padrão continua 15 min; fica no guard compartilhado com as coletas. Antes, uma parada na confirmação ou numa checagem cobrava 15 min de espera a cada tentativa da homologação.

## Unreleased — PR 68 (relatório de ONUs offline há mais de X horas)
- `GET /v1/onus/offline?min_hours=24&olt_id=&pon_path=&include_stale=&format=json|csv&limit=` (inventory:read, somente leitura, sem migração): as ONUs fora do ar há pelo menos X horas, as mais antigas primeiro, por OLT/PON, com exportação CSV. O início da queda traz a BASE (`transition_observed` exato; `since_last_online` = no máximo isso); ONU nunca vista online só é contada em `excluded.unknown_start`; dado de OLT sem coleta recente fica fora (`excluded.stale`) salvo `include_stale=true`. Sem dado pessoal (serial, OLT, PON). CSV neutraliza fórmulas de planilha.


## Unreleased — "Last down time" da OLT
- Edge: lê por SNMP (somente leitura, lotes de 20) o "Last down time" das ONUs offline e envia `last_down_at` no snapshot.
- API: migração 0023 `onus.olt_down_at`; `GET /v1/onus/offline` ganha a base `olt_reported` (abaixo de `transition_observed`, acima de `since_last_online`). `down_since` não muda de significado.
- Edge: `last_down` (opcional, entrada CLI Huawei R015): lê o "Last down time" por SNMP depois da coleta CLI, no máximo 1×/h, só nas PONs com ONU offline; o horário vai como `last_down_at` no snapshot seguinte. Sem segunda entrada de OLT.
