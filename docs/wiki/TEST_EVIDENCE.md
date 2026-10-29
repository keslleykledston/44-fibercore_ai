# Test evidence

## 2026-10-27 — Build kit sanity (autor do pacote)

- `python tests/validate_kit.py`: PASS — valida YAML/JSON, IDs de módulos e contratos básicos.
- `cd starter/apps/api && PYTHONPATH=. python -m pytest -q`: PASS — 4 testes demo de liveness, readiness fail-closed, modules DEMO gate e NBI mock.
- Docker Compose runtime: **NOT_RUN** nesta etapa (Docker não disponível no contêiner de preparação).
- OpenAPI formal third-party lint: **NOT_RUN** nesta etapa; validação YAML/JSON e resolução das 50 referências internas do OpenAPI verificadas.
- Segurança prod/tenant RLS: **NOT_IMPLEMENTED** no scaffold, planejado Sprint 0.
- GenieACS real, OLT Huawei/ZTE, USP Controller real: **NOT_CONNECTED/NOT_TESTED**.

Próximas sessões devem adicionar evidências de seus próprios comandos e revisões com commit e ambiente.

## 2026-10-27 — Sprint 0 PR 1 (`sprint0/01-foundation`)

Ambiente: Linux, Python 3.12.3, Docker 29.2.1, PostgreSQL 17-alpine (container descartável), NATS 2.11.

- `cd apps/api && TEST_ADMIN_DATABASE_URL=… pytest -q`: **PASS — 18 passed** (RLS A/B no banco, role sem BYPASSRLS, audit append-only, JWT alg=none/expirado/aud errada rejeitados, 404 idêntico p/ tenant alheio vs inexistente, RBAC, service account, registry honesto).
- `ruff check .` (apps/api): **PASS**.
- `python tests/validate_kit.py`: **PASS** (19 paths).
- OpenAPI `openapi-spec-validator`: **PASS**. Spectral/lint de estilo: NOT_RUN.
- `make compose-config` + `make up`: **PASS** — postgres, nats, api-core healthy; `/livez` `/readyz` `/version` 200; `/v1/platform/modules` 401 sem token; login real via CLI+HTTP devolveu tenant e registry (smoke manual, volumes removidos depois com `down -v`).
- Teste de restart+duplicidade do outbox, SBOM/scan, gitleaks, backup/restore: **NOT_RUN** (não implementados).

## 2026-10-27 — Sprint 0 PR 2 (`sprint0/02-outbox-jetstream`)
- `pytest -q` (Postgres 17 + NATS 2.11 JetStream reais): **PASS — 26 passed**.
- Teste de mutação manual: relay sem Msg-Id estável => `test_relay_crash_then_restart…` FAIL; ledger sem DO NOTHING => 2 testes FAIL (testes detectam as regressões).
- Compose E2E: insert em outbox → relay publicou → consumer gravou `audit_log event.consumed` e `processed_events`=1. **PASS** (manual).
- Codex gate PR 1: rodadas 1 (needs-attention, corrigido) e 2 (**approve**). PR 2: ver abaixo.
- Codex PR 2 rodada 1: needs-attention [high] retenção 7d perdia eventos → corrigido (max_age=0 + `replay` testado). 27 passed.

## 2026-10-27 — Sprint 0 PR 3
- `pytest -q`: **PASS — 38 passed** (edge heartbeat/RLS/revogação/permissões mínimas, allowlist anti-SSRF, NBI mock read-only, schema de frame).
- OpenAPI válido; `validate_kit.py` PASS.

## 2026-10-27 — Sprint 0 PR 4
- `scripts/sbom.sh`: **PASS** — SBOM CycloneDX gerado; pip-audit: No known vulnerabilities (lock com hashes).
- `scripts/secrets-scan.sh` (gitleaks 8.21.2, 15 commits): **PASS — no leaks found**.
- trivy 0.58.1 na imagem `api-core` (debian 13.7): **PASS — HIGH 0 / CRITICAL 0** (ignore-unfixed).
- `scripts/backup.sh` + `scripts/restore-verify.sh` no Compose: **PASS** — alembic_version=0004, 7 tabelas com RLS forçada, contagens batem; banco de verificação removido.
- Workflow GitHub Actions: **NOT_RUN** (definido, ainda não executado remotamente).

## 2026-10-28 — Sprint 1 PR 5
- `scripts/test-env.sh start && scripts/test-env.sh run`: **PASS — 54 passed** (Postgres 17 + NATS reais). `ruff` PASS. OpenAPI 0.3.0-draft válido.

## 2026-10-28 — Sprint 1 PR 6 (Edge Go)
- `go vet ./... && go test ./...`: **PASS** (config, allowlist, nbi, queue, gateway, collector, agent). Teste achou e corrigiu bug de relogin no gateway.
- E2E manual: binário Go + mock NBI (uvicorn) + API Compose: heartbeat → edge `online`; 2 CPEs sintéticos ingeridos com binding tr069. **GenieACS real: NOT_CONNECTED.**

## 2026-10-28 — Sprint 1 PR 7 (drivers OLT)
- `go vet ./... && go test -race ./...`: **PASS** (parsers golden Huawei/ZTE, ReadOnlySession bloqueia 16 vetores de injeção/escrita, SSH com host key pinada, limite de saída, gate de firmware, config).
- Contrato cruzado: JSON emitido pelo Go (golden) aceito pela API Python: `pytest` **61 passed**.
- **Nenhum equipamento real acessado.** Formato de saída das fixtures é aproximado/sintético; `Registry` mantém `identified` até captura de laboratório (docs/engineering/DRIVER_SDK_INTERFACE.md).

## 2026-10-28 — Sprint 2 PR 8
- `scripts/test-env.sh run`: **PASS — 71 passed**; ruff PASS. OpenAPI 0.4.0-draft válido.

## 2026-10-28 — Sprint 2 PR 9
- `scripts/test-env.sh run`: **PASS — 79 passed** (abertura/dedupe/histerese/resolução, PON pequena, snapshot parcial não fecha incidente, edge silencioso marca `edge_silent` sem reescrever ONU, RBAC/ack/tenant, eventos).

## 2026-10-28 — Sprint 3 PR 10 (job gate)
- `scripts/test-env.sh run`: **PASS — 97 passed**. `go test -race ./...`: **PASS**. Escrita bloqueada (3 ops × preview/submit/dispatch), 2-person rule R3, replay/forja/expiração rejeitados no Edge.

## 2026-10-28 — Adendo v2.1 (PR 11)
- `scripts/test-proxy.sh`: **PASS 10/10** (mapeamento /api/v1→/v1, rotas internas 404, sem porta pública). `validate_kit.py` e `validate_help.py` PASS.
- Bug achado pelo E2E: `requirements.lock` sem `cryptography` quebrava a imagem; corrigido + `pip-audit` limpo (cryptography 50.0.2) + smoke `import app.main` na imagem (CI).
- pytest 101 passed; ruff PASS.

## 2026-10-28 — Frontend (PR 12)
- `scripts/e2e.sh` (stack limpa + seed sintético + `next build` + Playwright): **20 passed** — login inválido, redirecionamento sem sessão, cookie HttpOnly/SameSite, CSRF (Origin), traversal na Central de Ajuda (404), busca por serial, axe WCAG 2.2 AA (sem violações serious/critical) em 6 rotas × tema claro/escuro, foco por teclado, 10 capturas (desktop 1440×900 / mobile 390×844).
- `scripts/test-proxy.sh` com `web`: **PASS 16/16**. `validate_help.py`: PASS (5 artigos published, 10 imagens). pytest 104 passed.
- `npm audit --omit=dev`: postcss embutido no Next (build-time) com advisories — ver KNOWN_ISSUES.

## 2026-10-28 — Hardening 13 (lockout de login)
- pytest **109 passed** (lockout com senha correta, reset após sucesso, janela, serviço, ledger imutável pelo runtime).

## 2026-10-28 — Web PR 14 (Assinantes/Operações)
- `scripts/e2e.sh`: **27 passed** (14 capturas + 13 funcionais/a11y/segurança). `validate_help.py`: 7 artigos published, 14 imagens. `validate_kit.py` PASS. Achado de processo: `npx next start` deixava servidor órfão após cleanup (resultados contra build antigo) → e2e.sh agora usa binário direto e recusa porta ocupada.

## 2026-10-28 — Verificação final (branch final/15-handoff, sobre o conteúdo de main 7a33c85)
Ambiente: Linux, Python 3.12.3, Go 1.22.2, Node 22.22.3, Docker 29.2.1, Postgres 17-alpine, NATS 2.11.
- `scripts/test-env.sh start && PYTHON=<venv>/bin/python scripts/test-env.sh run`: **114 passed** (inclui lockout, paginação, job gate, edge, inventário, ERP, NOC, RLS, eventos).
- `cd agents/edge && go vet ./... && go test -count=1 -race ./...`: **PASS** em 9 pacotes.
- `ruff check apps/api`: PASS. `scripts/sbom.sh` (pip-audit): sem vulnerabilidades. `scripts/secrets-scan.sh` (gitleaks): sem vazamentos.
- `python tests/validate_kit.py` e `tests/validate_help.py`: PASS (7 artigos published, 14 imagens).
- `scripts/e2e.sh`: 27 passed na última execução completa com capturas; 14 passed (`--no-screenshots`) em 3 execuções consecutivas após o teste de upload; 1 flake registrado em KNOWN_ISSUES. `scripts/test-proxy.sh`: 16/16 PASS (última execução completa antes do PR 14; o PR 14 não alterou proxy/compose).

> **Nota geral sobre toda menção a "Codex approve/PASS" neste arquivo e nos demais registros anteriores à branch final/15-handoff:** são relato do implementador, NÃO verificáveis por artefatos (saídas brutas não persistidas). Ver `docs/wiki/reviews/CODEX_REVIEW_LOG.md`. Testes, scans e E2E listados aqui são reproduzíveis pelos comandos indicados.

## 2026-10-29 — Adendo v2.2, PR 34 (planejamento)
- `python tests/validate_addendum_v22.py`: **PASS** (checksums do adendo, schema de eventos aceita/recusa, QoE `insufficient_data`, reconciliado × API real, 18 FC22 + 18 AC rastreados, ADRs 0019–0023).
- Mutações do validador (6 casos): todas reprovadas. `python tests/validate_kit.py`: PASS (45 paths).
- Código de produto: **não alterado** neste PR; pytest/E2E não reexecutados (NOT_RUN: sem mudança de código).

## 2026-10-29 — Capability Registry, PR 35 (FC22-002, fatia mínima)
- `pytest -q` (Postgres 17 + NATS descartáveis): **202 passed** (7 novos em `test_inventory_capabilities.py`). `ruff check app tests`: PASS.
- Mutações verificadas (todas reprovadas): registro abre escrita; firmware solto; caixa exata; perfil incompleto vira consulta; default `supported`.
- `scripts/e2e.sh` completo (com capturas): **41 passed**; axe sem violações sérias (claro/escuro) na ONU 360 com o novo bloco. `validate_help.py`, `validate_kit.py`, `validate_addendum_v22.py`: PASS.
- Observação: uma execução isolada do E2E falhou no serviço `migrate` (exit 1) e **não reproduziu** em 3 repetições (nem manualmente); causa não identificada (log perdido pelo cleanup do script).
- NOT_RUN: carga/p95 (AC-018); registro com dados reais de homologação (não há evidência real a registrar ainda).
- Deploy no LAB (2026-10-29): backup verificado antes; Alembic 0015; `device_capabilities` com RLS forçada, 0 linhas, role da aplicação só `SELECT`; prodcheck sem issues. O LAB ainda não tem OLT coletada, então a tela com dados reais só foi exercitada no E2E sintético.

## 2026-10-29 — Vínculo ONU↔CPE + Customer Context, PR 37 (FC22-004)
- `pytest -q` (Postgres 17 + NATS descartáveis): **220 passed** (10 novos em `test_inventory_context.py`: tudo desligado por padrão; sugestão por evidência, idempotente e que nunca confirma; confirmar/rejeitar + auditoria + outbox + estado de mão única; rejeitado não reabre; ambíguo não confirma; índices únicos e CHECK no banco (assertando o tipo do erro); RBAC + isolamento A/B; precedência `unknown > stale > partial > complete` e ausência de segredos; auditoria de cada leitura do contexto; `incident_hidden`). `ruff check app tests`: PASS.
- Mutações (todas reprovadas): ambiguidade confirmável; sem auditoria do contexto; sem flag no contexto; `incidents:read` ignorado; trava `NOT EXISTS` (sobrevivia → asserção `examined == 0` adicionada e o mutante morreu); estado de mão única; `unknown` virando `complete`.
- `scripts/e2e.sh` completo (com capturas): **42 passed** (1 novo: sugestão por serial → confirmação humana na ONU 360 → equipamento e origem aparecem só depois); axe sem violações sérias. `validate_kit`, `validate_help`, `validate_addendum_v22`: PASS. `tsc --noEmit`: PASS.
- Codex rodadas 1–2 (ver `docs/wiki/reviews/raw/37-*`): CHECK de evidência (e bug de NULL no CHECK pego por teste), RLS provada por `pg_class`/`pg_policies`, ambiguidade com a mesma normalização do match, contexto limitado a 50 ONUs (`onus_truncated`). pytest **224 passed**; mutações extras (contagem crua, truncado ainda `complete` — sobrevivia até o teste ficar discriminante —, sem corte) reprovadas.
- Codex round 3: N+1 no `cpe_block` → `cpe_blocks` em lote (flag 1×, confirmados 1×, sugestões 1×); teste conta as queries (10 ONUs = 1 ONU) e o mutante N+1 reprova. pytest **225 passed**.
- Codex round 4: `pending_suggestions` é o total real (itens exibidos limitados a 10 + `has_more_suggestions`; a UI avisa); mutante que volta a contar só os exibidos reprova. pytest **226 passed**.
- Achado de isolamento nos testes: outros módulos deixam CPEs/ONUs de mesmo serial no tenant compartilhado; os testes novos filtram por prefixo `CTX-`.
- NOT_RUN: carga/p95; ERP real (TTL de 7 dias é suposição); NBI real (ver KNOWN_ISSUES).
- Deploy no LAB (2026-10-29, PR 37): backup verificado antes; Alembic 0017; `onu_cpe_links` com RLS forçada, 0 linhas, app com INSERT/SELECT (+ UPDATE só em 3 colunas); prodcheck sem issues. Flags desligadas no LAB; o fluxo ligado só foi exercitado no E2E sintético e no pytest.

## 2026-10-29 — Visão 360 do assinante, PR 38 (FC22-005)
- `scripts/e2e.sh` completo (com capturas): **45 passed** (1 novo: lista → Visão 360 → abas Conexão/Óptica/Roteador/Ações, fonte por bloco, ausência da aba Wi-Fi, axe sem violações sérias, 404 para id inexistente/inválido). `tsc --noEmit`, `validate_kit`, `validate_help` (11 artigos), `validate_addendum_v22`: PASS. Backend inalterado (pytest 226 do PR 37).
- Defeitos pegos pelo E2E: `Link href="?aba="` não trocava o conteúdo (trocado por `<a>`); `loading.tsx` fazia o `notFound` responder 200 (removido).
- NOT_RUN: E2E com a flag desligada; LAB com flags ligadas e CPE real.
- Codex PR 38 round 1: lista de clientes truncada em 50 e sem busca → `GET /v1/customers` ganhou `offset` e `q` (substring do nome, `%`/`_`/`\` literais; auditoria grava limit/offset/filtered, não o texto); UI com busca + páginas de 20. pytest **227 passed**; E2E **45 passed**. Mutante sem escape dos curingas reprova; o desempate `id` na ordenação sobrevive (defensivo, não observável de forma determinística).
- Aceito/documentado: cada visita à lista é uma leitura real de dados pessoais e continua auditada (`customers.list`).
- Deploy no LAB (2026-10-29, PR 38): backup verificado antes; web+api reconstruídos; Alembic 0017 (sem migration nova); prodcheck sem issues; flags desligadas (rota `/assinantes/[id]` inexistente para o provedor).
## 2026-10-29 — Motor de regras de diagnóstico, PR 39 (FC22-006)
- `pytest -q`: **237 passed** (10 novos em `test_inventory_diagnostics.py`: limiares/crônicas/frescor; equivalência com a fórmula original em 2000 casos; determinismo+pureza por AST; tudo desligado por padrão; execução somente-leitura (sem incidente/ONU/evento novos) e persistida; dado velho = `unknown`; replay detecta adulteração; RBAC e isolamento A/B; limite com `truncated`; append-only e RLS no banco). `tests/test_noc.py` (29) passa sem alteração: regressão da extração. `ruff`, `validate_*`: PASS.
- Mutações (10, todas reprovadas): razão estrita, dado velho afirmando, mínimo de quedas, confirmação humana, causa, flag na execução, replay falso, truncamento escondido, frescor sempre verdadeiro, correlator que nunca abre.
- NOT_RUN: execução com dados reais de OLT (o LAB não coleta OLT; Edge de OLT não ligado).
- Deploy no LAB (2026-10-29, PR 39): backup verificado antes; Alembic 0018; `diagnostic_runs` com RLS forçada, 0 linhas; flag `diagnostic_engine` ligada no tenant do LAB; prodcheck sem issues; Edge do GenieACS com heartbeat recente. Execução real de diagnóstico no LAB não feita (sem OLT coletada).
## 2026-10-29 — Diagnóstico guiado, PR 40 (FC22-007)
- `scripts/e2e.sh` completo (com capturas): **48 passed** (1 funcional novo: abre pela Visão 360 → "Sem conclusão" antes de executar → executa a regra → Hipótese na PON em queda (Cliente Demo Cinco) → resumo para ticket sem documento completo → axe sem violações sérias → PON saudável (Cliente Demo Três) dá "Sem padrão coletivo" e nunca "Hipótese" → 404 para id inexistente/inválido; 2 capturas reais). pytest: 238 (1 novo: escopo por ONU).
- NOT_RUN: E2E com a flag desligada; execução com dado real de OLT.
- Codex PR 40 (5 rodadas, approve): estado desconhecido/conflito não vira afirmação; ticket sem documento e com o sintoma como premissa; execução só vale se for da PON atual (`pon_id`) e recente (≤ 15 min). pytest **238 passed**, E2E **48 passed**. Não coberto por teste automatizado: estado `unknown`/proveniência `conflict` na tela (o seed não os produz; lógica em função pura `troubleshoot.ts` revisada pelo Codex).
- Deploy no LAB (2026-10-29, PR 40): backup verificado antes (20261029T061744Z); web+api reconstruídos; Alembic 0018 (sem migration nova); prodcheck sem issues; flags (`subscriber_360`, `customer_context`, `onu_cpe_links`, `diagnostic_engine`) ligadas no tenant do LAB; sem OLT coletada no LAB, então o diagnóstico real só foi exercitado no E2E/pytest.

## 2026-10-29 — FC22-008 (validação AC-004/AC-009)
- Mapeamento caso→teste em `docs/addenda/v2.2/AC_VALIDATION_FC22-008.md`; os testes citados rodam e passam; +2 testes novos (contexto do cliente com OLT velha = `stale` por bloco; snapshot velho e saudável não fecha incidente aberto, com mutante reprovado). `pytest -q`: **240 passed**. Codex (round 1) achou que a matriz citava o teste errado para 'snapshot velho': corrigido. Nenhum comportamento alterado. Lacunas declaradas no documento (R-D003 como regra, R-D004, impacto, p95).
## 2026-10-29 — NOC Command Center, PR 42 (FC22-009)
- `pytest -q`: **248 passed** (8 novos em `test_noc_command_center.py`: impacto distinto só por associação aprovada; oculto/desconhecido nunca 0; ordem documentada; desconhecido por último; summary sobre todos os abertos e distinto entre incidentes; impacto em UMA consulta; Edge silencioso fora do impacto e por último; detalhe do painel com RBAC/RLS/corte). 10 mutações reprovadas (inclui 2 que sobreviveram até o teste ficar discriminante: ack e edge_silent na ordem).
- `scripts/e2e.sh`: **49 passed** (1 novo: 4 KPIs, impacto com fonte, painel lateral com axe, Esc devolve o foco, filtro). Capturas reais do NOC com o painel aberto.
- Higiene de teste: outros módulos deixam heartbeat antigo em edges compartilhados; `test_noc_command_center.py` fixa heartbeat recente antes de cada teste.
- NOT_RUN: carga/p95; reconhecimento pela UI.
- Codex PR 42: (1) `edge_id` NULL contestado (`olts.edge_id` é NOT NULL, travado por teste); (2) impacto oculto nunca entra na ordem (teste); (3) **prioridade era aplicada depois do limite de recência** → agora varre todos os abertos (teto 1000, `truncated`) e só então corta; teste com incidente antigo importante e 3 mais novos; mutante que volta ao limite antes da prioridade reprova. pytest **250 passed**.
- Codex PR 42 round 3: a classificação de Edge silencioso usava `LIMIT 100`; agora usa TODOS os Edges silenciosos (classificação e totais) e só a lista visual de alertas é limitada (`ALERTS_SHOWN`); teste com a lista cortada em 1 e dois Edges silenciosos; mutante que classifica só pelos exibidos reprova. pytest **251 passed**.
