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
