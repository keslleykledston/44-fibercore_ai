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
- Deploy no LAB (2026-10-29, PR 42): backup verificado antes (20261029T064505Z); web+api reconstruídos (sem migration nova, Alembic 0018); prodcheck sem issues; Edge do GenieACS continua coletando a cada 5 min (6 CPEs; 37 placeholders descartados).

## 2026-10-29 — Edge → OLT, guard de ritmo (PR 43)
- `cd agents/edge && go vet ./... && go test ./...`: PASS (novos: intervalo/cooldown CLI, restart com arquivo de estado, tentativa morta no meio, arquivo corrompido/`null`, timestamps absurdos com restart repetido, falha ao gravar = não disca, CLI+SNMP do mesmo host compartilham o guard, config `collect_seconds`/`cooldown_seconds`, `DeviceKey`, duplicidade de equipamento, IP literal, `StateFiles`, singleton).
- Mutation check: sem persistência do guard → 2 testes de restart falham; chave por nome em vez de host → 3 testes falham.
- Codex PR 43: 6 rodadas até approve (ver CODEX_REVIEW_LOG).

## 2026-10-29 — Reconhecer incidente e busca de cliente no ⌘K (PR 45)
- `scripts/e2e.sh`: **51 passed** (2 novos em `noc-ack-and-search.spec.ts`, projeto `posteriores`: reconhecer pelo painel com axe, botão some, fila e indicador "Não reconhecidos" diminuem e persistem após reload; busca de cliente só com 3+ letras, sem documento na lista, abre a Visão 360). Reexecução após a correção do Codex: 27 passed no modo funcional.
- Nota: o spec novo não rodava no primeiro intento porque o `playwright.config.ts` só casava `app.spec.ts`/`help-screenshots.spec.ts`; corrigido com o projeto `posteriores` (depende de `funcional`).
- NOT_RUN: teste com papel sem `incidents:ack` pela UI (a API tem teste de 403); teste de carga da busca.

## 2026-10-29 — SD-PR-01 contratos (PR 47)
- `make test-api`: **270 passed** (251 anteriores + 19 em `test_sd001_contracts.py`): schemas válidos e fixtures conformes; payloads malformados rejeitados; fixture não inventa valor para o não suportado; sobreposição sem colisão de caminho/operationId com o canônico; nenhuma rota do SD-001 existe na API; todo POST exige Idempotency-Key e o tenant vem do cabeçalho validado; 202 nunca promete execução; eventos sem dado pessoal; as quatro flags existem e estão desligadas; ADR-0025 Accepted; ação/conclusão sem evidência rejeitada; PSK/MAC/chave=valor rejeitados nos campos de evidência, narrativa, aprovação (só código), ids e Idempotency-Key; parâmetros de ação estritos por tipo.
- Mutation check (jsonschema direto): sem `minItems` na evidência da ação a ação vazia passa; com `value` string livre o PSK passa — os testes pegam os dois.
- Codex PR 47: 6 rodadas até approve (ver CODEX_REVIEW_LOG). Limite aceito e documentado: texto narrativo do copiloto só tem filtro parcial no schema; o controle real (redação na origem e antes de persistir) é requisito do PR que habilitar o copiloto.
- `validate_kit`, `validate_addendum_v22`, `validate_help`: PASS. `secrets-scan`: nenhum vazamento. `ruff`: só os 5 E501 antigos das migrações 0013–0015 (arquivos protegidos, não tocados).
- NOT_RUN: o `validate_bundle.py` do pacote (conteúdo baixado é dado não confiável; a validação equivalente está nos testes acima).

## 2026-10-29 — Leitor passivo de parâmetros (PR 48)
- `cd agents/edge && go vet ./... && go test ./...`: PASS. Novos em `internal/nbi/params_test.go`: lista só de folhas exatas, sem nome sensível e sem ancestral de outro; extração mantém só os 5 valores permitidos mesmo com SSID/senha/usuário/`KeyPassphrase` no documento (o segredo nunca aparece na saída); valores hostis sob caminhos permitidos (texto em enum, caixa trocada, número fora da faixa, sem/ com `_timestamp` inválido, objeto, nulo) rejeitados e contados; `CachedParams` é GET em `/devices`, projeção exata, sem `tasks`; falha fechada em 500/lixo.
- Mutation check: caminho sensível na lista → 2 testes falham; enum aceitando qualquer texto → 1 teste falha.
- `make test-api`: **271 passed** (teste cruzado: estados/métricas que o Edge emite ⊂ contrato).
- Medição na LAB (somente nomes de caminho, sem valores): 43 dispositivos, 5 com árvore (3 TR-098, 2 TR-181), nenhum com WAN/Wi-Fi/PPP. NOT_RUN: leitura real de WAN/Wi-Fi (não existe no cache; depende da decisão do ADR-SD-002 item 4).
- Codex PR 48: 2 rodadas até approve (ver CODEX_REVIEW_LOG). `CachedParams` em lotes de 25 ids, teto de 5000 por chamada; teste de lotes e rejeições sem tocar a rede.

## 2026-10-29 — Catálogo de consultas da OLT (PR 49)
- `cd agents/edge && go vet ./... && go test ./...`: PASS. Novos em `internal/olt/query_test.go`: catálogo só de `display`, sem verbo de escrita, renderiza no limite dos parâmetros, linha sem separadores; parâmetros fora de faixa ou usados fora do escopo recusados; só consultas validadas passam na allowlist até habilitação, e injeção (`; reload`, pipe, quebra de linha, parâmetro extra) nunca passa; sequência `enable, config, interface gpon, comando, quit` (e `quit` mesmo com falha); recusa antes de tocar o equipamento (id desconhecido, não habilitada, parâmetro ruim, outro firmware/modelo, comando livre); rejeição do equipamento, paginação e saída acima de 256 KiB falham fechado.
- Mutation check: política que permite tudo → 2 testes falham; entrada de catálogo com `|` → o teste do catálogo falha. O `Sprintf` com argumentos sobrando foi pego pela própria verificação de segurança (renderizava `%!(EXTRA…)`); trocado por substituição explícita.
- NOT_RUN: nenhuma consulta nova foi executada na OLT real (inerte por decisão do ADR-0026).
- Codex PR 49: 6 rodadas até approve (ver CODEX_REVIEW_LOG). Endurecimentos além do catálogo: allowlist do perfil R015 não herda mais a genérica (porta 0–15, slot 0–17, frame 0, números canônicos); `config.Load` recusa `pon_ports` fora desses limites no perfil R015; `Snapshot` valida antes de qualquer comando; `RunQuery` identifica a sessão (`display version`) em vez de aceitar identidade do chamador. Testes novos: limites via `Allowed`, zero comandos para porta inválida, identidade falsa/ilegível.

## 2026-10-29 — Leitura ativa de parâmetros (PR 50)
- `cd agents/edge && go vet ./... && go test ./...`: PASS. Novos: ACS falso confirma que só sai `getParameterValues` com nomes ⊂ lista fechada (5 grupos TR-098), `%` literal do id escapado uma vez, tarefa em fila/falha removida (e id inventado pelo ACS nunca vira DELETE), recusa SEM tarefa para dispositivo desconhecido/ambíguo/sem modelo/placeholder/injeção no id, parada na primeira tarefa rejeitada, varredura do código-fonte contra outros nomes de tarefa; guard: por dispositivo, por hora, persistência após reinício, 0600, id não em claro, falha fechada (corrompido/ilegível/sem configuração), datas futuras ignoradas; envelope: `target_ref` assinado, validado e só em `refresh`; agente: refresher antes da coleta, falha sem repassar erro bruto/IP/id, recusa quando desligado, refresh legado inalterado; config: `refresh_tasks` exige NBI e jobs.
- `make test-api`: **273 passed** (2 novos: `target_ref` assinado no refresh de CPE; sem binding TR-069 = sem referência).
- Codex PR 50: 4 rodadas até approve (ver CODEX_REVIEW_LOG). Testes extras: falha de DELETE (500/404/403) para na 1ª tarefa; id de tarefa inventado nunca vira DELETE e o refresh falha; POST 500/502/503/504/408/429/409/413 e queda de conexão ⇒ retenção; 400/401/403/404/405/422 ⇒ erro sem retenção; retenção por dispositivo, persistida e em memória quando a gravação falha.

## 2026-10-29 — Ensaio real do refresh ativo e reconciliação (PR 51)
- Ensaio na LAB (Edge 0.3.0-lab-4e17c1a, job `refresh` assinado em CPE de teste `FCTEST`): o ACS criou a tarefa e fechou a conexão (EOF); o Edge falhou o job, reteve o dispositivo e logou localmente, como projetado. Foi preciso remover à mão a tarefa pendente (1 nome, deste dispositivo, criada naquela chamada); depois: 3 tarefas e 1 falha antigas, nenhuma do FCTEST. Um job para dispositivo desconhecido do ACS falhou com a categoria "device unknown" sem criar tarefa.
- `go vet ./... && go test ./...`: PASS com ACS falso com estado: nada fica para trás em fila/falha/id escondido/id inventado/corpo ilegível; EOF depois de criar a tarefa é reconciliado sem retenção; só apaga tarefas desta chamada (mesmo dispositivo, nome, parâmetros e carimbo recente; outras ficam); falha de DELETE/listagem ou DELETE que não apaga ⇒ retenção; recusas inequívocas do NBI não listam nada.
- Mutation check: ignorar o carimbo ⇒ 1 teste falha; remover a confirmação por nova listagem ⇒ 1 teste falha.
- NOT_RUN: refresh concluído com dado real de WAN/Wi-Fi (os CPEs de teste não responderam à conexão); novo ensaio após o deploy desta correção.
- Codex PR 51: 7 rodadas até approve (ver CODEX_REVIEW_LOG). `go test -race ./...` PASS (inclui chamadas concorrentes serializadas, pré-checagem de pendente, id tardio/nunca visível, ausência não provada, listagem grande demais, duplicata, ACS que ignora a consulta).

## 2026-10-29 — Deploy na LAB do refresh ativo e segundo ensaio real
- Deploy: backup `fibercore-20261029T180130Z.dump` antes; `make up-prod` (API com `target_ref`; sem migração nova); chave de assinatura de jobs criada no `.env.prod` (0600, nunca impressa) porque a LAB não tinha (despacho de jobs estava desabilitado); Edge `0.3.1-lab-caa3e41` no host do GenieACS com `jobs_enabled`, `refresh_tasks` e só a chave pública. A coleta da OLT/NBI seguiu normal (guard da OLT persistido).
- Ensaio 2 (CPE de teste `FCTEST`, job `refresh` assinado): o ACS criou a tarefa e fechou a conexão (EOF, ~21 s, o CPE não respondeu à conexão); o Edge achou a tarefa pelo id/listagem, apagou, confirmou e falhou o job com a causa ("acs request failed"), sem retenção. Estado do ACS depois: 3 tarefas e 1 falha **antigas** (preexistentes), nenhuma do FCTEST.
- NOT_RUN: refresh concluído com dado real de WAN/Wi-Fi — nenhum dos 6 CPEs cadastrados (FCTEST, probe, ACME, MikroTik hAP lite) respondeu à conexão e as 37 ONTs reais aparecem só como `DISCOVERYSERVICE` (identidade placeholder, recusada por desenho). Contas de serviço de ensaio (`lab-refresh-trial*`, papel `noc_n2`) ficaram criadas sem segredo guardado.

## Ensaio do refresh ativo com ONT de bancada (LAB, 2026-10-29) — resultado parcial, sem dado real

- ONT Huawei EG8145V5 de bancada, sem cliente; configurada no TR-069 (intervalo 300 s, credenciais CWMP do ACS). O ACS passou a exigir autenticação CWMP (antes aceitava qualquer Inform): sem credencial, o log do CWMP mostrava `Authentication failure`. Com credencial, o Inform periódico é aceito e o Edge cria o CPE com vínculo TR-069 no cloud.
- Connection Request (ACS → ONT): a ONT só aceita se a origem do pedido coincide com o endereço de ACS configurado nela. Com a ACS URL apontando para um endereço traduzido (NAT) e o ACS saindo com o IP interno, a ONT respondia `401` SEM desafio Digest; depois de alinhar a ACS URL ao IP interno do ACS, a resposta passou a ter `WWW-Authenticate: Digest`. Um Connection Request manual com a credencial guardada no ACS devolveu 200 e a ONT fez Inform com evento `6 CONNECTION REQUEST`.
- Refresh pelo Edge (job assinado, `refresh_tasks` ligado): job `SUCCEEDED`, `groups=5 completed=0 faulted=0 queued=5 cleaned=5 readable_metrics=0`; ACS terminou no baseline (3 tarefas antigas, nenhuma da ONT). O POST da tarefa com `connection_request` retorna 202 em ~30–40 ms e a ONT NÃO abre sessão, ao contrário do Connection Request manual: causa ainda NÃO determinada (o log de acesso do NBI/CWMP não registra o motivo; leitura do log de erro exige root).
- NOT_RUN: nenhum dado real de WAN/Wi-Fi foi lido; `cpe_state` continua sem fonte real.
- Causa do refresh sem dado, determinada (com `sudo` somente leitura no host do ACS): o ACS tem `cwmp.connectionRequestAuth` com um par fixo `AUTH("…","…")`; o POST de tarefa com `connection_request` devolve `202` com o motivo `Connection request error: Unexpected status code 401` — a ONT usa credencial de Connection Request diferente (padrão de fábrica) da que o ACS envia. O Connection Request manual com a credencial informada pela própria ONT funcionou (200). Correção, a cargo do responsável: igualar o usuário/senha de Connection Request da ONT ao par de `cwmp.connectionRequestAuth` (ou ajustar a expressão no ACS). Nada foi alterado no ACS.
- **Refresh ativo com dado real (ONT Huawei EG8145V5 de bancada, LAB, 2026-10-29)**: após igualar a credencial de Connection Request da ONT à de `cwmp.connectionRequestAuth`, o job `refresh` (assinado, R0, `refresh_tasks` ligado) terminou `SUCCEEDED` com `groups=5 completed=5 faulted=0 queued=0 cleaned=0; readable_metrics=5 rejected=0`. ACS no baseline (3 tarefas antigas, nenhuma da ONT, 0 faults).
  - Folhas da lista fechada lidas no cache do ACS: estado do link físico da WAN (Up), `Enable`/`Channel` de 2 rádios Wi-Fi (rádio 1 canal 1; rádio 5 canal 36). Nenhum segredo na lista.
  - Lacuna: `ConnectionStatus`/`Uptime` das conexões WAN (PPP/IP) NÃO vieram — a lista fechada cobre `WANConnectionDevice.{1,2}.{WANPPPConnection,WANIPConnection}.{1,2}` e esta ONT não expôs valor nesses caminhos (instância/numeração a verificar em captura sanitizada do firmware, sem ampliar a lista às cegas).
  - Ainda NOT_RUN: transporte `cpe_state` Edge→cloud (migração 0019) e uso do dado nas regras R-D002..004.
- **Refresh com 11 grupos (instâncias WAN 1..4) na ONT de bancada, LAB, 2026-10-29 (Edge 0.3.2-lab-0d741fa):** `completed=11 faulted=0 queued=0 cleaned=0; readable_metrics=7`. Estado da conexão PPP (instância 3) e uptime lidos além do link e dos 2 rádios. Faults no ACS antes/depois: 1/1 (nenhum da ONT); tarefas 3/3. `go vet ./... && go test -race ./...` PASS (Edge). Contrato dos 11 grupos fixado por teste.

## 2026-10-30 — `cpe_state` (PR 53) na LAB, com dado real
- Backup `fibercore-20261030T002127Z.dump` antes; `make up-prod`: migração 0019 aplicada (`alembic_version`=0019, tabela `cpe_state` criada), API saudável.
- Edge `0.4.0-lab-d17f128` no host do GenieACS (jobs + `refresh_tasks` mantidos). Na primeira rodada de coleta chegaram 7 linhas em `cpe_state` da ONT Huawei EG8145V5 de bancada: link da WAN Up; conexão PPP (instância 3) Connected e uptime; rádios 1 e 5 Enabled com canais 1 e 36; `captured_at` é a hora de leitura guardada pelo ACS, `received_at` a hora do servidor.
- `make test-api` 306 passed; `go vet ./... && go test -race ./...` PASS (Edge); ruff só os 5 E501 antigos das migrações 0013–0015; secrets-scan sem vazamento; validate_help e validate_addendum_v22 PASS. Contrato OpenAPI atualizado (YAML válido).
- Ainda NOT_RUN: uso do estado por regra (R-D002…R-D004) e no Visão 360; leitura do estado com mais de uma ONT; CPE real de cliente (nenhum foi tocado).

## 2026-10-30 — R-D002 v1 (PR 54, ADR-0027)
- `make test-api` 316 passed (testes unitários da regra, propriedade com 800 casos e API: leitura somente leitura sem incidente/estado/evento, replay reproduzível, entradas sem serial nem texto livre, isolamento entre tenants, escopos exclusivos, vínculo ONU↔CPE só confirmado). ruff só os 5 E501 antigos; validate_addendum_v22 PASS; secrets-scan sem vazamento.
- NOT_RUN (no momento deste registro): execução na LAB (corrigido abaixo: a flag `diagnostic_engine` já estava ligada na LAB pelo responsável) e tela de troubleshooting para a R-D002.

## 2026-10-30 — diagnostic_jobs passivos (SD-PR-03, PR 55, ADR-0028)
- `make test-api` 328 passed (job completo com evidência e achados validados contra o esquema do contrato; só leitura: sem incidente, estado, evento nem `diagnostic_runs`; nada de serial/nome/documento gravado; idempotência e 409; dado antigo/ausente = `insufficient_evidence`; queda coletiva com o agregado citado e a PON/janela no envelope; propriedade com 600 casos; replay; isolamento entre tenants; append-only no banco; pureza por AST). `validate_addendum_v22` PASS (contrato canônico reconciliado com a API). ruff só os 5 E501 antigos; secrets-scan sem vazamento.
- Conserto de teste: a verificação "nenhuma rota do SD-001 existe" lia `app.routes` (só `/openapi.json` neste FastAPI) e era vazia; agora usa o OpenAPI gerado.
- NOT_RUN: execução do job na LAB (`smart_diagnostics_jobs` segue DESLIGADA; ligar é decisão do responsável; `diagnostic_engine` já estava ligada) e tela de troubleshooting que consuma o job.

## 2026-10-30 — implantação na LAB do PR 54 e do PR 55; R-D002 com dado real
- Backup `fibercore-20261030T012112Z.dump` antes; `make up-prod`: migração 0020 aplicada (`alembic_version`=0020, tabela `diagnostic_jobs`), API saudável. Flags na LAB: `customer_context`, `diagnostic_engine`, `onu_cpe_links`, `subscriber_360` ligadas (pelo responsável, antes); `smart_diagnostics_jobs` desligada.
- R-D002 v1 executada na LAB (conta de serviço de ensaio, `POST /v1/diagnostics/runs`) sobre a ONT Huawei EG8145V5 de bancada, depois de um `refresh` real (11 grupos, `completed=11 faulted=0 readable_metrics=7`) e da entrega do estado à nuvem (idade mínima 6 s): achado `observed` — "o CPE informa uma conexão WAN estabelecida"; enlace Up e conexão Connected, ambos recentes; sem vínculo ONU↔CPE confirmado (contexto da ONU não considerado); replay `reproducible: true`. A regra não afirmou queda nenhuma, como esperado para a ONT de bancada saudável.
- Ainda NOT_RUN: R-D002 com o caso de conexão caída (só em teste automatizado) e job diagnóstico na LAB.

## 2026-10-30 — job diagnóstico passivo REAL na LAB (PR 55, ADR-0028)
- A pedido do responsável: flag `smart_diagnostics_jobs` ligada na LAB (`feature-set`, owner CLI; `diagnostic_engine` já estava ligada).
- Fixture de bancada (NÃO é cliente real): cliente `BANCADA K3G (teste)` (`erp_source=bancada-lab`), associação `approved` à ONU da ONT de bancada (a mesma ONT aparece na OLT real e no ACS, mesmo serial) e vínculo ONU↔CPE `confirmed`, ambos marcados na evidência como fixture criada a pedido do responsável; reviewer = o admin da LAB.
- Depois de um `refresh` real (11 grupos, `completed=11 faulted=0 readable_metrics=7`) e da entrega do estado à nuvem, `POST /v1/diagnostics/jobs` (conta de serviço de ensaio, modo passivo): `status=complete`, `data_quality=fresh`, `reproducible=true`, regras R-D001 v1 e R-D002 v1. Evidências (todas `available`): ONU online e RX -13,04 dBm (OLT real), enlace WAN Up, conexão PPP Connected e uptime (CPE, `genieacs_nbi`). Nenhum achado: a ONT de bancada está saudável e o job não inventou nada.
- Ainda NOT_RUN: job com queda real (só em teste automatizado) e tela que consuma o job.

## 2026-10-30 — gate de bancada, lado nuvem (PR 56, ADR-0030 H0)
- `make test-api` 354 passed (cada uma das condições do gate recusa com o seu motivo; flag desligada mantém `operation_not_homologated`; firmware exato; gate global intacto para `set_wifi_ssid`/`provision_onu`; autorização consumida com a aprovação, de uso único e sem rastro quando a aprovação é recusada; envelope assinado com `authorization_id`/`owner_epoch`/`target_ref` e validade curta; janela reverificada no despacho; trava de escrita em falha, UNKNOWN e job não reportado; role do app sem escrita nas listas de bancada; isolamento entre tenants; owner CLI; evidência checada). ruff só os 5 E501 antigos; validate_addendum_v22 PASS; secrets-scan sem vazamento.
- NOT_RUN: qualquer escrita (o caminho está desligado por `EDGE_SUPPORT=False` até o PR do Edge). Nada foi enviado a equipamento.

## 2026-10-30 — gate de bancada, lado Edge + código do H2 (PR 57, ADR-0030)
- `cd agents/edge && go vet ./... && go test -race ./...` PASS em todos os pacotes; `make test-api` 361 passed; secrets-scan sem vazamento; validate_addendum_v22 PASS.
- Provas por teste: ACS simulado com um dispositivo de PRODUÇÃO do mesmo modelo — o reboot só chega ao id de bancada, qualquer divergência de OUI/classe/serial/duplicata/offline/tarefa pendente recusa sem escrever; claim durável (reinício lê UNKNOWN, nunca reexecuta; epoch não recua; store ilegível = recusa); lease assinada (Python assina, Go verifica — golden `tests/fixtures/edge/bench_lease_signed.golden.json`; adulterada, de outra chave, de outro edge/tenant, vencida, mais antiga que a atual → recusa e retira); envelope/janela vencidos antes do envio → nada enviado e autorização não gasta; resultado ambíguo nunca é reenviado e a tarefa própria é removida; execução fora do laço de poll.
- NOT_RUN: qualquer reboot real. Nenhum comando foi enviado a equipamento. Migração 0021 e o Edge novo ainda não estão na LAB.

## 2026-10-30 — primeira execução do gate de bancada (PR 58, ADR-0030 emenda)
- `make test-api` 373 passed (identified+first_run abre o gate e a autorização é de uso único; identified sem first_run, entrada ausente, `unknown` → `capability_not_observed`; banco recusa `supported` sem evidência; mudança do registro entre aprovação e despacho cancela; com `observed` só a autorização normal abre e a first_run não; first_run consumida cancela se `observed` aparecer; CLI recusa sem entrada `identified`, com `observed` e uma segunda aberta; escopo de tenant das consultas; exclusão mútua promoção × avaliação). validate PASS; secrets-scan sem vazamento.
- NOT_RUN: qualquer escrita em equipamento.

## 2026-10-30 — deploy na LAB do gate de bancada (PR 56–59) e firmware do CPE (PR 59)
- Backup `fibercore-20261030T030646Z.dump` antes; `make up-prod` (API + web saudáveis); `alembic current` = 0022 (head). Edge do host do GenieACS trocado só no binário (`0.5.0-lab-c3edd1a`, configuração inalterada: SEM seção `bench`, portanto escritas desligadas; flag `bench_writes` continua desligada).
- PR 59: `go test -race ./...` PASS (formatos de firmware aceitos/rejeitados, snapshot com e sem firmware).
- NOT_RUN: qualquer escrita em equipamento; Edge com o firmware (0.5.x+PR 59) ainda a implantar.

## 2026-10-30 — H2 `reboot_cpe` REAL na ONT de bancada (ADR-0030)
- Autorização prévia `first_run` do responsável (03:30:49–03:45:49 UTC) → job `c6ed9338-…` criado, aprovado pelo solicitante (emenda do ADR) → despachado 03:31:38 → o Edge releu a identidade no ACS, reservou o ritmo, gravou o claim e enviou UMA tarefa `reboot` → `_lastBoot` novo 03:32:41 → `SUCCEEDED` 03:32:48 com pós-checagem.
- Verificação independente: só 1 dispositivo do ACS com boot novo (a ONT de bancada); nenhuma tarefa `reboot` restante; claim `DONE`; autorização `consumed`; sem trava. O responsável observou a ONU voltar online na OLT e aceitou o resultado.
- Registro: `reboot_cpe`/tr069 do perfil Huawei EG8145V5 V5R019C10S350 promovido a `observed` com a evidência `docs/wiki/bench/H2-reboot_cpe-2026-10-30.md` (checada pelo owner CLI). `certified` NÃO concedida.
- NOT_RUN: segunda execução (pedida pelo responsável, com autorização normal); H3 (SSID) e H4 (OLT).

## 2026-10-30 — H2 repetido com autorização NORMAL (sem `first_run`)
- Autorização `b43be4aa-…` (janela 03:47:04–04:02:04 UTC), job `2d14e3be-5f4f-4d6b-aed0-79c7f1cbb8df`: aprovado 04:01:34, despachado 04:01:54 (o Edge só liberou o ritmo às 04:01:31 — 30 min após o reboot anterior), `_lastBoot` novo 04:02:56, `SUCCEEDED` com pós-checagem; claim `DONE`, autorização `consumed`, alvo sem trava. Só a ONT de bancada teve boot novo.
- Valida o caminho de rotina: com `reboot_cpe` `observed`, a autorização normal abre o gate. A primeira autorização desta repetição (`19e9380b-…`) expirou sem uso porque foi registrada antes de o ritmo abrir (o Edge recusaria o envio).
- As contas de serviço de ensaio (`lab-bench-h2-*`, `lab-refresh-trial*`) foram desativadas.

## 2026-10-30 — H3 `set_wifi_ssid`, código (PR 61)
- `make test-api` 385 passed; `go vet ./... && go test -race ./...` PASS. Provas por teste (ACS simulado com a bancada E um CPE de produção do mesmo modelo): troca → leitura de volta → restauração → leitura de volta, só no CPE de bancada e só a folha `WLANConfiguration.1.SSID`; registro de restauração gravado (0600) antes da troca e mantido se a restauração falhar; formato do SSID recusado fora de `^BANCADA-[A-Z0-9]{1,16}$` no preview, no gate, no CLI, no envelope e antes do envio; autorização presa ao SSID exato; `params` cobertos pela assinatura; tarefa enfileirada removida; resultado ambíguo nunca reenviado; restauração enfileirada removida.
- NOT_RUN: nenhuma manobra H3 real. Pendentes: deploy na LAB, registro `set_wifi_ssid` identified e a autorização do responsável.

## 2026-10-30 — H3 `set_wifi_ssid` REAL na ONT de bancada (ADR-0030)
- Tentativa 1 (job `121d1ad6-…`, 04:55): recusada ANTES de qualquer escrita; causa ambiental (credencial de Connection Request da ONT desalinhada do ACS); claim `FAILED`, SSID intacto, fila vazia. Responsável realinhou; alvo destravado após conferir.
- Tentativa 2 (job `7b050c8f-…`, 05:12, autorização `first_run` 6833fa43-…): `SUCCEEDED` em ~10 s; 5 requisições ao NBI, todas à ONT de bancada (ler, trocar para `BANCADA-H3`, ler, restaurar, ler); SSIDs 2,4 GHz e 5 GHz iguais aos de antes (conferido no ACS); arquivo de restauração removido; claim `DONE`.
- Registro: `set_wifi_ssid`/tr069 do perfil Huawei EG8145V5 V5R019C10S350 promovido a `observed` com a evidência `docs/wiki/bench/H3-set_wifi_ssid-2026-10-30.md` (aceita pelo responsável). `certified` NÃO concedida.

## 2026-10-30 — H4 `onu_reset` / `onu_deactivate`, código (PR 63); caracterização da OLT
- Caracterização somente leitura da OLT (1 sessão CLI supervisionada, allowlist exata, guard renovado antes): ONU de bancada `0/0/14`, ONT-ID 10, serial GPON exatamente igual ao do CPE; sintaxe `ont reset|deactivate|activate <porta> <ontid>` (e o perigo do argumento `all`). Arquivo: `docs/wiki/bench/H1-olt-caracterizacao-2026-10-30.md`.
- `make test-api` 392 passed; `go vet ./... && go test -race ./...` PASS. Provas por teste (OLT simulada): lista fechada e exata de comandos (nenhum `all`/`graceful`/outra porta/outro ID passa); identidade (uma só ONU, F/S/P, ONT-ID, serial de 16 hex, online/normal/match/active) lida duas vezes antes de gastar o claim; claim e ritmo só depois da identidade; prazo checado no instante do envio; `onu_deactivate` SEMPRE reativa e verifica; reset sem retorno e reativação recusada são reportados e travam; nada é repetido; o guard da OLT é o mesmo das coletas.
- NOT_RUN: qualquer manobra real na OLT. Pendentes: deploy na LAB, configuração `bench.olt` no Edge, registro `identified` por operação (perfil da OLT) e a autorização do responsável.

## 2026-10-30 — H4: primeira tentativa de `onu_reset` recusada com segurança; confirmação do CLI da OLT
- Job `6c5d99e1-…` (05:49): o Edge confirmou a identidade, gastou o claim e enviou `ont reset 14 10`; o CLI perguntou `Are you sure to reset the ONT(s)? (y/n)[n]:`; o Edge NÃO responde a perguntas (fail-closed), fechou a sessão e reportou `FAILED`. A ONU NÃO reiniciou (ACS: `_lastBoot` inalterado 04:02:56). Alvo travado, autorização consumida.
- Sonda supervisionada (06:06): a pergunta do reset foi lida e respondida "n"; `ont deactivate`/`ont activate` NÃO pedem confirmação — o `deactivate` da sonda executou e foi desfeito (~8 s, sem reboot da ONT). Incidente de conduta registrado em `docs/wiki/bench/H1-olt-caracterizacao-2026-10-30.md`.
- PR 65: o Edge passa a responder UMA vez a pergunta observada do reset (e só ela). `go test -race ./...` PASS.

## 2026-10-30 — H4: segunda tentativa de `onu_reset` (job `6b8e7c3f-…`, 06:18): o reset RODOU, o acompanhamento falhou
- O Edge confirmou a identidade, enviou `ont reset 14 10`, respondeu "y" UMA vez à pergunta observada e o CLI executou: o ACS registrou `1 BOOT` da ONT de bancada às 06:20:09 (≈1 min depois do comando) e ela voltou a informar. O Edge, porém, leu o eco do próprio "y" na linha da pergunta como uma segunda pergunta, abortou o acompanhamento e reportou `FAILED` ("outcome unknown"): bug do Edge (PR 66), não da OLT. Alvo travado; autorização `3b98c1b1-…` consumida.
- O reset só conta como homologado depois de um job `SUCCEEDED` com a pós-checagem pela OLT (próxima autorização).

## 2026-10-30 — H4 REAL na ONU de bancada: `onu_reset` e `onu_deactivate` (ADR-0030)
- `onu_reset`: job `e83e7313-…` `SUCCEEDED` (≈60 s): identidade lida duas vezes na OLT na mesma sessão, `ont reset 14 10` com a confirmação observada respondida uma vez, ONU de volta `online` com novo horário de subida (OLT) e novo boot da ONT (ACS); só a ONT de bancada reiniciou.
- `onu_deactivate`: job `68e7c250-…` `SUCCEEDED` (≈30 s): `ont deactivate 14 10` observado, `ont activate 14 10` SEMPRE enviado depois e `active`/`online` lidos de volta na OLT; a ONT não reiniciou.
- Registro: `onu_reset` e `onu_deactivate` (protocolo `olt`, perfil huawei MA5608T MA5600V800R015C00) promovidos a `observed` com as evidências `H4-onu_reset-2026-10-30.md` e `H4-onu_deactivate-2026-10-30.md` (aceitas pelo responsável). `certified` NÃO concedida.
- Quatro tentativas até o primeiro `SUCCEEDED` do reset (duas recusadas pelo guard da OLT antes de enviar, uma parada na confirmação, uma com bug do eco da resposta, corrigido no PR 66): ver o histórico na evidência.

## 2026-10-30 — relatório de ONUs offline há mais de X horas (PR 68)
- `make test-api` 398 passed; validate PASS. Provas por teste: ordenação (mais antigas primeiro), base explícita (`transition_observed` / `since_last_online`), ONU nunca vista online só contada, filtros por OLT e PON (padrão estrito), dado velho (ONU ou OLT, inclusive horário ausente) fora e contado antes do limit, isolamento entre tenants, CSV com fórmulas neutralizadas e cabeçalhos de exclusão, sem dado pessoal.


## 2026-10-30 — "Last down time" da OLT para ONUs offline (SNMP → `olt_down_at`)
- `make test-api` 400 passed; `go vet` + `go test -race ./...` (Edge) PASS; validate PASS; secrets-scan sem vazamentos.
- Edge: leitura SNMP em lotes (≤20 OIDs por Get) só das ONUs offline; falha da leitura nunca derruba o snapshot; `parseDateAndTime` estrito (11 bytes, ano 2010–2100, data válida, fuso ≤14 h → UTC).
- Cloud: coluna própria `onus.olt_down_at` (migração 0023), separada de `down_since` (a correlação de incidentes continua lendo só transições observadas). Provas por teste: valor guardado, nunca no futuro, ONU online não tem, leitura ausente mantém o último, leitura nova substitui, voltar online apaga, hora sem fuso → 422, transição observada vence (`basis` = `transition_observed`), ONU sem nada continua só em `excluded.unknown_start`.
- Base nova do relatório: `olt_reported`. Limite declarado: o relógio da OLT do LAB está ~7 min atrás do real. Ainda NÃO há leitura real na OLT do LAB (próximo passo, supervisionado e só leitura).

## 2026-10-30 — canal SNMP "last_down" dentro da entrada CLI do Edge
- Edge `go vet` + `go test -race ./...` PASS. Config: `TestOLTLastDownConfig` (outro dispositivo, fora da allowlist, sem community, intervalo < 900 s, pace < 1000 ms, requests > 1000, nome de host, perfil sem R015 → recusados). Coletor: lê só as PONs com ONU offline; o horário viaja no snapshot CLI seguinte; esquecido quando a ONU volta e não herdado por nova queda; falha SNMP nunca falha a coleta e o retry espera o próximo intervalo; sem ONU offline não há tráfego SNMP. Mutação (desligar `applyLastDown`) faz dois testes falharem.
- Motivo do desenho: o config proíbe duas entradas para a mesma OLT (uma entrada SNMP com outro nome criaria uma segunda OLT na nuvem), então o SNMP vira canal opcional da entrada CLI.
- Leitura focada (Codex, rodada 4): `HuaweiSNMP.LastDowns` pede só o "last down time" (col 23) e o serial (col 3) das ONUs-alvo, 1 requisição por 5 ONUs (limite de 10 OIDs por GET do transporte; a primeira leva 4 + a conferência da porta); hora só vale se o serial respondido é o do alvo; ONT-ID vem da listagem CLI R015 (`ONU.OntID`). Testes: serial trocado → sem horário; ONU online nunca é pedida; 12 ONUs = 3 requisições; ifIndex que não é porta GPON → nada lido; alvos de duas portas/ID fora da faixa → recusados. Coletor: leitura em segundo plano (a rodada não espera), uma por snapshot CLI, resposta descartada se chegou snapshot CLI mais novo, cursor de PON entre execuções, estourar o próprio orçamento não é falha do agente.
- Travamento do dispositivo (Codex, rodada 6): a leitura do "last down time" segura o mesmo travamento "em andamento" da OLT que a coleta CLI e as manobras da bancada (ritmo e cooldown continuam em chaves separadas); orçamento da leitura 3 min (típico ~1 min). Teste: com a leitura em curso, `Exclusive` e a coleta CLI veem "already running". Consequência operacional: não autorizar manobra da bancada nos ~3 min após uma coleta CLI em que a leitura rode (no máximo 1×/h).
- Medição na OLT real (2026-10-30, somente leitura, via relay): `LastDowns` com pace de 1 s → o 1.º pedido (4 ONUs + conferência da porta) respondeu com horários e seriais corretos, o 2.º deu timeout e o agente ficou mudo alguns minutos; a primeira leitura do Edge (pace 1 s, logo após a coleta CLI) também deu timeout. Com pace de 2 s: 12 alvos = 3 pedidos, todos respondidos, 6 s, sem erro. Padrão do `last_down` passou a 2 s (`LastDownConfig.Pace()`).
- Segunda tentativa real (08:42, pace 2 s): de novo timeout em todos os pedidos, a partir do fim da coleta CLI (08:41:38); leituras manuais 3+ min depois de uma sessão CLI responderam normalmente. Novo parâmetro `last_down.settle_seconds` (padrão 240 s, 60..600): a leitura SNMP só começa depois da espera, em segundo plano, uma por snapshot CLI. Teste: nada é enviado ao agente durante a espera, outro tick não cria segunda leitura, exatamente uma leitura depois.
- Resultado da homologação do canal `last_down` na OLT real (2026-10-30): NÃO homologado. Quatro leituras do Edge deram timeout (07:35, 08:41, 09:05 com espera de 4 min, 09:36 na porta 0/0/13, ONT-IDs 1..4, primeiro pedido), enquanto o mesmo código Go, direto do host, leu corretamente a porta 0/0/14 (3 pedidos, 6 s) e leituras manuais de OIDs individuais da 0/0/13 responderam. O agente SNMP da MA5608T fica mudo sem relação clara com o ritmo (pace 1 s, 2 s e 3 s: mudou depois de 2 a 7 pedidos) e uma sessão CLI recente não explica tudo; o agente é compartilhado com o monitoramento do ISP, então a investigação parou. Canal desligado no LAB (`config.json.pre-lastdown-off` guarda a configuração; arquivo da community removido do host). Código, API (`olt_down_at`, base `olt_reported`) e testes seguem no repositório e valem para qualquer fonte do horário.

## 2026-10-30 — "Last down time" por CLI (`down_times`, PR 74/75)
- Decisão do responsável: opção (b), pela CLI, sem tocar no agente SNMP. Edge `go vet` + `go test -race ./...` PASS (parser contra a captura real sanitizada, rejeições, allowlist só com opt-in, estado por ONU, relatório não bloqueante).
- Codex: PR 74 rodada 1 achou HIGH (registro mais novo malformado herdava queda antiga) → corrigido, rodada 2 approve; PR 75 (log de diagnóstico) rodada 1 HIGH (callback na rota da coleta) → corrigido, rodada 2 approve.
- LAB real (somente leitura, na MESMA sessão CLI da coleta de 15 min, `max_per_round` 15): coleta passou de ~157 s para ~190 s; log `olt last down times picked=15 read=15 found=14` (1 sem registro utilizável) em duas coletas seguidas.
- Concordância CLI × SNMP: as primeiras ONUs da lista já tinham horário vindo das leituras SNMP parciais anteriores; depois das coletas por CLI o hash (serial + horário) de todas as ONUs com `olt_down_at` no banco ficou IDÊNTICO, ou seja, o horário do `register-info` coincide com o do SNMP nas ONUs lidas pelos dois caminhos.
- Estado: 83 de 295 ONUs fora do ar com `olt_down_at`; as demais são preenchidas ~14 por coleta (≈ 4 h), pois o Edge ainda relê as já preenchidas em cada reinício. Limite declarado: ONU que volta e cai entre duas coletas mantém o horário antigo até ser vista online.

## 2026-10-30 — tela "ONUs offline" (`/rede/offline`, PR 76)
- `make test-api` 401 passed (novo: guarda de fórmula do CSV com espaço/controle antes do operador); `tsc --noEmit` limpo; `next build` OK; teste puro dos filtros PASS; validate-help PASS (artigo `rede/onus-offline` em rascunho: sem capturas reais ainda).
- Contra a API REAL do LAB (build local do Next em porta própria, login com a conta de acesso do frontend, sem imprimir dado): relatório renderizado; 83 ONUs listadas, todas com base "Informado pela OLT" (horário que a própria OLT informa, lido por CLI); 206 sem horário de início; CSV 200 com cabeçalho esperado e 84 linhas; CSV sem sessão 401. O E2E de navegador completo (stack de seed) NÃO foi rodado nesta máquina: `scripts/e2e.sh` derruba a stack dev e usa a porta 18420 da API do LAB.

## 2026-10-30 — fase Dispositivos, entregas 1–3 (somente leitura, PR 77)
- `make test-api` 402 passed (novo: `GET /v1/cpes/{id}` igual ao item da lista, 404 entre provedores, 404 para id inexistente, 422 para id inválido); `make validate` PASS; `tsc --noEmit` e `next build` OK; 3 artigos de ajuda em rascunho (sem capturas reais).
- Contra a API REAL do LAB (build local do Next, login com a conta de acesso do frontend, sem imprimir dado): lista com 7 CPEs, detalhe abre (identidade, estado, capacidades), filtro por fabricante funciona, Edges com 1 Edge, matriz com 6 perfis; axe (WCAG 2.2 AA) sem violação séria/crítica em `/dispositivos`, detalhe, Edges, Capacidades e `/rede/offline`; id inválido → 404. E2E de navegador completo (stack de seed) NÃO rodado aqui (derrubaria a stack dev e usa a porta da API do LAB); os testes novos estão em `apps/web/e2e/app.spec.ts`.

## 2026-10-30 — RBAC, entrega 1: catálogo único + inventário + matriz gerada (PR 78, ADR-0031)
- `make test-api` 419 passed; `make validate` PASS. Sem mudança de comportamento: a matriz esperada por papel foi congelada a partir do comportamento anterior e o teste a compara com o código.
- Mutações reprovadas: (1) dar `jobs:read` ao `noc_n1` → falham o teste da matriz esperada e o do documento gerado; (2) rota nova sem permissão → falha o teste das listas nomeadas. Inventário igual às operações do OpenAPI do próprio app; as 3 listas (pública, autentica a própria conta, só sessão) ligadas ao mecanismo verificado; as rotas sem permissão devolvem 401 sem credencial e com token inválido.
- ADR-0031 continua Proposed (decisões do responsável de 2026-10-30 registradas; em aberto: escopo por OLT/site e a confirmação da dispensa de SoD da bancada). Construção feita até aqui: só a entrega 1.

## 2026-10-30 — RBAC, entrega 2: `access_manager` e troca de papel com travas (PR 79, ADR-0031)
- `make test-api` 439 passed; `make validate` PASS; matriz gerada em dia; secrets-scan sem vazamentos.
- Provas por teste (banco real): política pura igual a um oráculo independente em todas as combinações; só `isp_admin` e `access_manager` têm `members:manage` e o gestor não tem poder operacional (403 em inventário, clientes, jobs, CPEs); `access_manager` sem MFA não faz nada (403 `mfa_enrolment_required`) mesmo com a política vazia; recusas com código estável; sessões do alvo encerradas na hora (token antigo 401), em todos os provedores da conta; auditoria com origem, destino e motivo; evento no outbox.
- Segurança no banco: `fibercore_app` sem UPDATE na coluna e sem EXECUTE na função (inclusive forjando `app.user_id`/`app.tenant_id`); só `fibercore_rbac` executa; regras em SQL iguais ao `role_policy`; gatilhos mantêm ≥1 `isp_admin` ativo (troca, delete, desativação da conta); sem a conexão dedicada a rota responde 503.
- Concorrência (com mutação): duas trocas simultâneas deixam exatamente 1 administrador; troca de papel × desativação da conta sem deadlock. Mutações reprovadas: EXECUTE também para o app, função sem as travas, sem a checagem de alvo protegido, sem reler o ator sob a trava, sem encerrar sessões.
- Decisões do responsável (2026-10-30): só papéis de sistema por ora; Gestor de Acesso (`access_manager`) ou `isp_admin` concedem; MFA recente 10 min e delegação de 8 h (entrega 5); escopo por OLT/site depois; dispensa de SoD da bancada mantida.

## 2026-10-30 — RBAC, entrega 3: tela Papéis e permissões (PR 80, ADR-0031)
- `make test-api` 441 passed; `make validate` PASS; `tsc` e `next build` OK; matriz gerada em dia.
- Executado de ponta a ponta numa stack EFÊMERA (Postgres descartável + API + Next locais; nada do LAB): o administrador abre a tela, vê a matriz, troca o papel de outra pessoa pela interface com motivo, o papel muda na tabela, o histórico mostra a mudança e o banco tem a auditoria (`engineer → noc_n1`, motivo gravado); a própria linha não tem botão; um papel sem permissão (Atendimento) vê cada seção degradar sem erro e sem botão de troca.
- axe (WCAG 2.2 AA) sem violação séria/crítica em TODAS as rotas, tema claro e escuro, incluindo as telas novas. Isso achou um defeito real: botões de ação com texto branco fixo no tema escuro (contraste baixo) em `/rede/offline`, `/dispositivos`, `OnuTable` e na tela nova, corrigidos para o token `--on-accent`. A execução também achou um filtro do BFF que recusava `noc_n1`.
- Os testes E2E novos estão em `apps/web/e2e/app.spec.ts`; o conjunto completo do `scripts/e2e.sh` (stack de seed do compose) NÃO foi rodado aqui. Os dois testes que dependem de dado de seed (ONUs offline e Dispositivos) não rodaram na stack efêmera, que não tem OLT/CPE.

## RBAC entrega 5 — MFA recente e delegação da plataforma (PR 81)
- `make test-api` 462 passed (21 novos em `tests/test_rbac_delegation_mfa.py`); `make validate` PASS; segredos: sem vazamento; matriz gerada em dia; `tsc` e `next build` OK. `ruff check apps/api` já falhava na base (74 achados, quase todos E501) e passou a 102 com este PR; não foi tratado aqui.
- Cobertura: o login com MFA grava a prova; o refresh a carrega sem renovar; janela de 10 min, prova no futuro recusada; step-up (código errado, sessão de outra pessoa, sem bearer, código de uso único, sessão encerrada, sem MFA ativo = 409, limite de tentativas = 429); delegação dá só `tenant:read`, vence no instante pelo relógio do banco com o mesmo token, revogação imediata, renovação substitui, conta não operadora = mesma resposta que inexistente, já-membro = 409, autodelegação = 422, outro provedor nem enxerga (RLS), desmarcar o operador ou desativar a conta encerra, o papel `platform_support` não pode mais ser membership (CHECK), prazo máximo de 8 h e imutabilidade garantidos pelo banco, auditoria e outbox.
- Stack EFÊMERA: Playwright `Papéis e permissões` (troca de papel e concessão/encerramento de acesso temporário) passou; axe claro e escuro passou; com `MFA_RECENT_ENFORCE=true` e administrador com MFA, a tela pediu o segundo fator no meio da troca de papel, recusou código errado, aceitou um código de recuperação e a ação concluiu (papel mudou e histórico gravado).
- Codex: rodada 1 = 1 HIGH (a chave vinha desligada por padrão) → corrigido (padrão LIGADO; desligar é exceção explícita com aviso no log; o LAB tem a exceção declarada no `.env.prod` até o administrador ativar o MFA); rodada 2 = approve, sem achados (`raw/130-*`, `raw/131-*`).
- Não feito: via `api` da autorização de bancada (decisão aberta: quem detém `bench:authorize`).

## Dispositivos entrega 4 — ações na tela do CPE (PR 82)
- `make test-api` 476 passed (14 novos em `tests/test_inventory_device_actions.py`); `make validate` PASS; `tsc` e `next build` OK; matriz gerada em dia.
- Cobertura: a tela só oferece o que o registro tem `observed`/`certified` para o perfil exato (`identified`/`unknown` não contam); papel sem permissão não vê oferta e não consegue pedir; pedido sem entrada observada → 409 e NENHUM job criado; com o portão global (`HOMOLOGATED_WRITES` vazio) e o `bench_writes` desligado, o pedido vira job CANCELADO com `operation_not_homologated`, nada chega ao Edge (204) e a autorização do responsável fica intacta; alvo de bancada com autorização → job PENDING_APPROVAL (a autorização só é gasta na aprovação), clique duplo/retry com a mesma chave devolve o mesmo job, chave reutilizada com outra operação → 409; alvo fora da bancada → `target_not_bench`; nome do Wi-Fi só no formato do catálogo; reinício sem parâmetros; CPE de outro provedor = 404.
- Stack EFÊMERA (CPE e capacidade fictícios): o CPE sem registro mostra as duas ações como indisponíveis, com o motivo; o CPE observado mostra o botão do reinício e o Wi-Fi indisponível; o pedido (clique duplo) criou UM job CANCELADO com a mensagem “não está homologada… Nada foi enviado” e auditoria `device.action_blocked`. axe claro e escuro, na página e com o painel aberto, sem violação séria. O teste e2e do seed completo não foi estendido (depende de CPE com registro `observed`).

## Autorização de bancada pela API (PR 83, ADR-0031 2(e))
- Decisão do responsável: operador para cima autoriza a manobra de bancada, sem depender só do CLI do dono.
- `make test-api` 487 passed; novos: `tests/test_inventory_bench_authorize.py` (11): papéis × operações (catálogo = tabela Python = tabela SQL), registro curto/único/marcado `api`, expirada não bloqueia nova, pré-condições do alvo (não bancada, travado, chave desligada), autorizador não pode pedir nem aprovar (mutação que remove a regra FALHA), revogação (e a do dono não se remove), CLI do dono intacto, app role não executa as funções nem insere, CHECKs do banco, listagem sem e-mail para quem não lê membros, MFA recente e 503 sem conexão dedicada.
- Stack EFÊMERA: o Engenheiro vê o card, escolhe a manobra, autoriza, vê "Aberta… dada pelo painel por você", repetir é recusado com a mensagem certa e **Encerrar** funciona; axe claro e escuro, página e painel, sem violação séria.

## Equipe e acessos — redesenho e reconstrução (PR 84)
- `make test-api` 504 passed (17 novos em `tests/test_team_access.py`, mais ajustes); `make validate` PASS (84 caminhos); `tsc` e `next build` OK; segredos: sem vazamento.
- Cobertura nova: convite → aceitar → entrar (conta criada com a senha escolhida; token bruto não está no banco, só o hash); senha curta/fraca recusadas; link usado/revogado/vencido/inválido; conta existente prova a senha atual (erradas limitadas: a 6ª = 429, achado e corrigido por teste: a tentativa errada não era gravada porque a exceção desfazia a transação); regras de função (Gestor de acesso não convida Administrador; só quem gerencia pessoas convida); reemitir substitui; cancelar; redefinição por link (sessões antigas morrem; conta compartilhada = 409; protegido = 403; si mesmo = 403); remover (resolução do principal falha na hora; último Administrador fica); troca da própria senha; a role da aplicação não executa nenhuma função nem escreve nas tabelas; 503 sem a conexão dedicada; atividade em fatos, sem e-mail para quem não lê membros; toda permissão de papel humano tem capacidade explicada.
- Stack EFÊMERA (Playwright): redefinir verificação em 2 etapas pela nova tela; trocar função com "O que muda" e ver na Atividade; **convidar → pessoa abre o link sem sessão → cria a conta → entra → troca a própria senha → administrador reemite/cancela convites → remove a pessoa**; acesso temporário do suporte da plataforma. axe claro e escuro em todas as rotas (incluindo `/administracao/equipe` e as abas); sem rolagem horizontal no celular (390 px); capturas conferidas.
- Lovable: um projeto de protótipo (dados fictícios, nenhum segredo); adotadas a lista única com convites na mesma tabela, os selos de situação e os cartões no celular.

## onu_state_events — histórico de estado das ONUs (PR 85)
- `make test-api` 513 passed (10 novos em `tests/test_inventory_onu_history.py`; rodada 2 do Codex: ordem por `seq` com tempos empatados, `/unstable` ranqueado e filtrado no SQL, retenção `onu_state_events_prune`); `make validate` PASS (86 caminhos); `tsc` e `next build` OK.
- Cobertura: o gatilho registra só mudanças reais (mesmo estado de novo, snapshot mais antigo e repetição da mesma observação não registram nada); linha do tempo conhecida dá exatamente 2 quedas, 72 h fora e 240 h conhecidas (70%), e a janela menor recorta os trechos; `unknown` não conta como online nem como fora nem como queda; lista de instáveis (4 quedas aparece com `min_drops=3` e some com 5) e o relatório de offline traz `drops_30d`/`offline_hours_30d` (JSON e CSV); isolamento entre provedores, permissões (noc_n1 lê, auditor não), 404 e validação; a role da aplicação não escreve no histórico (INSERT/UPDATE/DELETE negados) e o gatilho SECURITY DEFINER continua gravando pelo ingest.
- Stack EFÊMERA com uma ONU fictícia que cai e volta: o cartão "Histórico (30 dias)" mostra 2 quedas, 2 d 6 h fora e 77,5% (confere com a conta: 54 h de 240 h conhecidas); a coluna "Últimos 30 dias" no relatório mostra "2 quedas · 2 d 6 h fora do ar"; axe claro e escuro sem violação séria.
- No LAB, a baseline da migração deve ter 1 linha por ONU, com `at` = instante da migração (conferido no deploy).

## olt_query — metade da nuvem (PR 86)
- `make test-api` 526 passed (13 novos em `tests/test_olt_query.py`: catálogo nuvem = Edge, escopo fechado, nada oferecido nem criado sem canal, flag sozinha não basta e a CLI recusa, intenção assinada e válida no schema do envelope, portões antes do job, idempotência e auditoria, cota por usuário, provedor e OLT, falha no submit não deixa job, portões refeitos no submit e no despacho, nada despachado sem canal); `go test ./...` do Edge PASS; `make validate` PASS.
- Nenhum equipamento tocado; a OLT real não foi consultada.

## olt_query — Edge: envelope e fila durável (PR 87)
- `go test ./...` do Edge PASS (inclui `go test -race ./internal/oltquery`, lock entre instâncias com mutação confirmada, arquivo corrompido em 8 formas); testes novos: intenção fechada por escopo (15 recusas), catálogo e hash pinados contra a nuvem, envelope `olt_query` (chave local, verificador, allowed_operations, hash trocado, campos de bancada, TTL), fila (ciclo e reinício, idempotência e limite, CLAIMED→UNKNOWN sem reexecução, orçamento por sessão e por hora, expiração e aborto, arquivo corrompido, resultado limitado, claims concorrentes, retenção de 24 h). Python: 14 passed em `tests/test_olt_query.py` (vetores pinados do lado da nuvem).
- Nada toca a OLT: a fila ainda não está ligada ao executor.

## olt_query — executor no Edge e resultado tipado (PR 88)
- `go test ./...` do Edge PASS (9 rodadas do Codex; inclui janela de tempo, entrega durável e recusa da nuvem): parsers contra as capturas reais (`display version`, `display board 0`) e 9 recusas; `Queries` em sessão simulada (uma sessão, nada de `enable`/`config` repetido, depois da coleta, recusa do equipamento aborta o lote sem afetar a coleta, sem parser nunca chega ao equipamento, sem `cloud_id` ou fila ilegível não roda, 5 por sessão); agente (enfileira, não executa; resultado tipado viaja depois; UNKNOWN; sem fila falha fechado; OLT alheia descartada); configuração (7 recusas). Python: testes novos de `data` (formato exato, 8 formatos inválidos viram FAILED sem armazenar, `board`, `data` fora de lugar).
- Sessão simulada com os arquivos REAIS de `testdata/.../MA5600V800R015C00`; a OLT real não foi consultada. Risco a verificar no ensaio supervisionado: o modo em que o equipamento real deixa a sessão após o snapshot (pressuposto: config).

## olt_query — arrendamento e geração de propriedade (PR 89)
- Python: arrendamento (OLTs do Edge, época, assinatura, outro Edge não recebe, sem flag/canal nada), época no envelope, transferência em duas fases pela CLI (consultas abertas terminam, sem despacho no meio, fase 2 recusada enquanto o arrendamento pode estar vivo, dono novo com época 2, não dá para terminar duas vezes) e a role da aplicação não consegue mover uma OLT. Edge: famílias de arrendamento isoladas, época só sobe e persiste, consulta de outra geração termina sozinha e a atual roda, arrendamento perdido entre a pergunta e o claim não envia nada, sem arrendamento nada é reivindicado.

## olt_query — ensaio supervisionado na OLT real do LAB (fatia 5, 2026-10-30)
- Autorização: do responsável, em 2026-10-30 ("autorizado fatia 5"). Escopo: `olt.version` e `olt.board`, uma por vez, pedidas pela API como o admin do LAB; nada de escrita; a consulta roda na MESMA sessão CLI da coleta periódica (sem login extra, guard de 15 min intacto). Instância única: no host do Edge há 1 processo `fibercore-edge` (lock de instância do próprio Edge); a confirmação de que nenhum outro host fala com a OLT é do responsável.
- Preparação: Edge reimplantado com o binário `0.1.0-lab-9242b01` e a coleta seguiu normal (191 s, 775 ONUs) com `olt_query` desligado; só então configuração `olt_query_enabled` + `cloud_id` + `olt_query` em `allowed_operations` (cópia `config.json.pre-oltquery`, reversão automática se o Edge não subisse) e flag do provedor ligada (backup antes: `fibercore-20261030T215228Z.dump`).
- `olt.version` (22:11 UTC): job SUCCEEDED; resultado tipado `{product: MA5608T, version: MA5600V800R015C00, patch: SPC100 HP1013, uptime_seconds: ~89 milhões}`. A consulta esperou ~8 min pela janela da coleta e rodou depois dos comandos dela; a coleta terminou normal (190 s) e o guard não mudou.
- `olt.board` (22:30 UTC): job SUCCEEDED; 5 placas (`H805GPFD` x2, `H801MCUD1` ativa, `H801MPWE` x2) e o slot 3 vazio, idêntico à captura de referência. Coleta seguinte normal (190 s); 775 ONUs; nenhum erro novo no log do Edge.
- Confirmado no equipamento real: o snapshot R015 deixa a sessão em modo config (`RunQueryInConfig` sem reenviar `enable`/`config` funcionou) e a fila do Edge terminou `REPORTED` nas duas.
- Observação: o envelope de `olt_query` vivia 10 min, mas as janelas da coleta são de 15 min; um pedido feito logo após uma janela podia expirar antes da próxima. Ajustado: envelope 20 min (o máximo que o Edge aceita) e job 22 min; pior espera medida pelo desenho = 15 min de intervalo + ~3 min de coleta ≈ 18,5 min.

## onu_state_events — medição com volume e retenção agendada
- Banco DESCARTÁVEL (nada toca o LAB): 30 000 ONUs e 1 230 000 eventos (40 mudanças por ONU em 400 dias), migrações até a 0029, role da aplicação com RLS. `GET /v1/onus/unstable` (consulta `_availability` sem filtro, `min_drops=3`, `limit=101`): janela de 30 dias, mediana 369 ms (pior 2,6 s com cache frio); janela de 365 dias, mediana 1,5 s (pior 2,1 s). Relatório offline (500 ONUs, 30 dias): 72 ms. Histórico de 1 ONU (365 dias): ~1 ms. O plano lê só os eventos da janela (índice `(tenant_id, at)`) e faz UMA busca indexada por ONU para o estado anterior à janela; o custo cresce com o número de ONUs do escopo, não com o tamanho da tabela. O LAB tem 781 eventos / 775 ONUs: ordens de grandeza abaixo.
- Retenção (procedimento e cron em `docs/operations/RETENTION.md`; medição reproduzível por `scripts/perf-onu-events.sh`): `scripts/retention-scheduled.sh` (chama `onu_state_events_prune(400)` como dono do banco, com `flock`, log `~/fibercore-backups/retention.log` 0600) instalado no cron do usuário às 03:45 (depois do backup das 03:15). Execução manual no LAB: `OK removidos=0 de 781 (keep_days=400)`.

## Tela de consultas da OLT (PR 94)
- `tsc` e `next build` OK; Playwright (projeto `consultas`) 4 passed em stack efêmera (axe sem violações sérias com a gaveta aberta; resultado com `<img onerror>` no lugar de um campo é descartado); a rota real BFF→API cria o job `olt_query` APPROVED com `{query_id, olt_ref, catalog_version}`; axe claro/escuro das rotas autenticadas (inclui `/rede`) passou. A LAB tem MFA no admin: a conferência visual lá é do responsável.

## Edge: modo captura supervisionada (PR 95, ADR-0032 item 1)
- `go vet ./...` limpo; `go test -count=1 ./...` verde em todos os pacotes do Edge.
- Novos testes: `oltquery` (`TestCaptureBudgetIsItsOwnClassAndFitsTheAggregate`: 2/sessão, 4/h, por OLT, sobrevive a reinício, janela de 1 h rola, não consome a classe sob demanda, teto agregado 8), `collector` (`olt_capture_test.go`: arquivo 0600 em diretório 0700 com a saída crua intacta, nada na fila de relatórios, execução única mesmo após reinício, só consultas listadas chegam ao equipamento, orçamento de 2 por sessão com o resto na próxima, recusa do equipamento encerra o lote e não se repete, varredura de 24 h e `.tmp-`, diretório cheio não executa, sem lease ou fila ilegível não executa), `config` (`TestOLTCaptureConfig`: PON/ONU só da bancada, duplicata, consulta desconhecida, parâmetros fora do escopo, >10, sem `olt_query_enabled`).
- Ainda NÃO executado no equipamento real: a captura do lote 1 acontece depois do merge e do reimplante do Edge, numa janela de coleta.

## ERP Hub — HubSoft primeiro (PR 96, HS-01 + HS-02; somente mocks)
- `tests/test_erp_hubsoft.py`: 28 testes (registro e ordem, URL/host/SSRF, resolução pública, arquivo de segredo, cliente de token com relógio e envio simulados: cache, renovação, 401 uma vez, 403, 429 curto/longo, 5xx com jitter, redirecionamento, resposta de token inválida, limitadores próprios, concorrência, isolamento de chave, ausência de segredo em erros; remetente HTTP com `MockTransport`: conecta no IP verificado, SNI/Host pelo nome, sem seguir redirecionamento, limite de corpo; API: flag desligada, validação, papéis e isolamento entre tenants, teste com segredo ausente/ok/401/403/429/503, endereço privado recusado, espaçamento de testes, segredo fora de resposta/log/auditoria, ligar só após teste saudável, desligar com a flag desligada, a role da aplicação não altera URL/ref/provedor nem apaga).
- Suíte completa do `apps/api`: 567 passed (primeira rodada com 1 falha esperada em `test_team_access`, corrigida ao acrescentar a capacidade "Conectar e testar o ERP" na tela de Equipe). `ruff` limpo. Matriz RBAC regenerada.
- NÃO verificado: qualquer comportamento real do HubSoft (formato exato do corpo do token, códigos de `retry_after`, limites efetivos). Isso exige ensaio real autorizado (checklist H1/H4).

## Captura supervisionada na OLT real do LAB — lote 1 (2026-10-31, ADR-0032)
- Edge `0.1.0-lab-76a52c0` com `capture` (olt.time, olt.sync, olt.temperature, olt.alarm.active, olt.autofind); coleta seguiu normal (190–199 s, 775 ONUs). Diretório `captures/` 0700 e arquivos 0600 conferidos por SFTP somente leitura.
- `olt.time` ok (63 B: a hora da OLT estava ~6 min atrás da hora real: por isso o relógio da OLT fica só dentro de `data`); `olt.sync` ok (35 B: "Standby board fault or not exist": a resposta não distingue reserva ausente de reserva com falha; a tela diz exatamente isso); `olt.temperature` ok (210 B, 3 placas); `olt.alarm.active` -> `paginated` (a captura marcou a tentativa e não repete); `olt.autofind` -> `budget` (4 capturas por hora por OLT: roda na primeira janela depois de 01:49 UTC).
- Testes: `go vet` + `go test ./...` PASS (parsers a partir das capturas reais e fechados contra saídas inválidas); `apps/api` `test_olt_query.py` 27 passed (formatos fechados do lote 1, catálogo da nuvem = catálogo do Edge, versão do catálogo e hash de intenção pinados nos dois lados); Playwright projeto `consultas` 6 passed na stack efêmera (inclui o caso novo; axe sem violações sérias).

## Cache primeiro das consultas à OLT (PR 98)
- `apps/api` `test_olt_cache.py` (9 testes) + `test_olt_query.py`: 36 passed. Cobrem: resultado de job alimenta o cache e o pedido seguinte não cria job; valor acima do TTL fica `stale` e pergunta de novo; `refresh` com cota própria; o cache obedece às comportas do job (flag desligada recusa até o dado guardado; papel sem permissão); isolamento entre tenants; resultado de Edge que deixou de ser dono não vira "último valor"; época anterior não regride o cache; resultado inválido não entra; temperatura alimenta a série; formato da chave de parâmetros.
- Playwright (projeto `consultas`, stack efêmera): 7 passed, incluindo o caso do dado guardado com "Atualizar agora" e axe sem violações sérias. `ruff` e `tsc` limpos; `next build` OK.

## ONT Configuration Manager — leitura (PR 99, FC24-01; somente mocks sintéticos)
- `apps/api` `test_ont_config.py` (21 testes) e suíte completa: 608 passed; `ruff` limpo. Cobrem: catálogo sem valor de senha nem caminho de dispositivo; validação de valores por campo (SSID de ≤32 bytes, IPv4, faixas, enums, vínculo rádio↔SSID); flag desligada recusa tudo; dispositivo desconhecido devolve `no_data` e formulário vazio (nada inventado); perfis `dualband`, `multi_ssid` (SSID 3 = 5 GHz por vínculo, não por posição), `no_wifi` (sem grupo Wi-Fi), `inactive_5g` ("banda não informada"); capacidades (`supported` só se observado, `write_allowed` falso mesmo com registro certificado, risco por capacidade, potência Wi-Fi sem unidade presumida); dado obsoleto (`partial_stale`) e fonte calada (`stale`); ingestão do Edge (tipada, a leitura mais nova vence, antigas ignoradas, nome fora do catálogo/senha/valor inválido/campo extra/futuro recusados, só o Edge dono do CPE); isolamento entre Edges e tenants; permissões (NOC N1 lê, auditor não) e auditoria só com contagem; óptica da OLT pelo vínculo confirmado; CHECK do banco contra nome de senha e FK entre tenants; CLI de perfis sintéticos; revisão estável.
- NÃO verificado: qualquer leitura de ONT/GenieACS real (o Edge ainda não reporta `cpe-config`); mapeamentos TR-098/TR-181 continuam candidatos.

## ONT Configuration Manager — sidebar (PR 100, FC24-02)
- `tsc` e `next build` OK; Playwright projeto `aparelho` na stack efêmera (API + Next reais, perfil sintético do CLI): 2 passed — sidebar não modal e só leitura (todos os campos `readonly`, nenhum botão de salvar/aplicar), dados sintéticos rotulados, óptica -19.4 dBm sem edição, troca de rede 2,4→5 GHz troca os campos, senha só "definida", Esc recolhe e devolve o foco, axe sem violações sérias; no celular (390×844) sem rolagem lateral. `validate_help.py` PASS. Corrigido durante a validação: o efeito de carga se cancelava a si mesmo (a tela ficava em "Carregando"), achado pelo e2e.
- NÃO feito: captura real para a ajuda (a ajuda segue em rascunho); fluxo `seed_demo.py` não foi reexecutado inteiro (usa Compose); a mesma preparação foi reproduzida na stack efêmera por script equivalente.

## ONU Quick Inspector (PR 101, UX 2.2)
- `tsc` e `next build` OK. Playwright projeto `inspetor` (stack efêmera com API + Next reais e dados semeados): 4 passed — painel largo não modal (PON/ACS/RX/identidade; dado velho fica neutro, LOS fica vermelho; trocar a ONU substitui o conteúdo; clicar de novo na mesma não fecha; Esc fecha e devolve o foco; axe sem violações sérias); resposta atrasada de outra ONU nunca aparece e falha do resumo (502) não derruba a lista; o BFF devolve o formato fechado por fonte (400 para id inválido, 404 para inexistente, nada de senha/PSK); celular: gaveta modal sem rolagem lateral. Com a flag DESLIGADA (prova pontual, 1 passed): o resumo antigo (`onu-summary`, foco de volta) segue como era e a chamada direta ao BFF recebe 403 `disabled`. Um resumo com `onu.id` de outra ONU é rejeitado pelo painel (coberto no caso do BFF).
- NÃO verificado: `e2e` completo do demo via Compose (`scripts/e2e.sh`) com o seed novo e `app.spec.ts` ajustado; papel sem `customers:read` (restrito) no e2e; captura real da ajuda.

## ONT Configuration Manager — pré-visualização de mudança (PR 102, FC24-03; somente mocks sintéticos)
- `apps/api` `test_ont_config_changes.py` (37 casos): a pré-visualização devolve diff `de → para`, risco, aprovações e bloqueios em ordem fixa, nunca `submittable`; a submissão devolve 409 `executed: false`, grava `blocked` e audita, sem criar job; com escrita habilitada, fonte real e dado fresco (monkeypatch) o pedido segue bloqueado por `executor_not_available`; 13 pedidos inválidos recusados com código estável (SSID > 32 bytes, instância de outro escopo, campo fora da capacidade, instância não observada, canal fora da faixa, LAN incompleta/máscara não contígua/endereço de broadcast, faixa DHCP invertida, senha em texto, capacidade óptica, sem mudança); a senha nunca é aceita, gravada nem ecoada; revisão velha → 409; R3 só para quem tem `ont_config:request_high`; auditor não pede; só quem pediu submete; R3 pede segundo fator recente quando `MFA_RECENT_ENFORCE` está ligado; outro tenant não vê; flag desligada recusa; pré-visualização vencida → 410; mudança da configuração depois do pedido aparece como `stale_revision` na submissão. Matriz RBAC regenerada; `ruff` limpo.
- NÃO verificado: qualquer execução (não existe); UI de pedido (não existe).

## Gestão de ONUs — layout Lovable (PR 103, ADR-0037)
- `tsc` e `next build` OK. Playwright na stack efêmera (API + Next reais, seed no formato do demo): `inspetor` 14 passed (inclui teclado: setas, Home/End e foco móvel em abas e filtros) (painel como coluna ao lado da lista sem esconder colunas — caixas de árvore, lista e painel em ordem e sem sobreposição; matriz de PONs com estado em texto e célula que leva à PON; árvore e trilha; filtros por estado e serial com contagem anunciada; abas Resumo/Aparelho/Histórico com troca de ONU voltando ao Resumo; aba Aparelho só com roteador confirmado, somente leitura; falha do histórico com nova tentativa; celular com gaveta; ONU 360° com trilha, painel frontal, LOS em texto, dado velho esvaziando o painel; axe sem violações sérias nos painéis), `aparelho` 2 passed, `consultas` 7 passed (testes ajustados: vários painéis/diálogos na página; flake do relógio falso corrigido).
- Flag DESLIGADA (prova pontual na stack efêmera, 1 passed): Rede volta ao inventário com a coluna de OLTs, sem matriz nem árvore; o resumo é o simples de antes; a ONU 360° sem trilha nem painel frontal.
- NÃO verificado: `app.spec.ts` completo com o seed do demo (Compose, `scripts/e2e.sh`): na stack efêmera 9 testes falham por dependerem de dados que o seed efêmero não cria (clientes/associações/CPEs de DEMOA0001) ou por violação preexistente de axe em `/dispositivos/capacidades` (`scrollable-region-focusable`), fora deste PR; capturas da ajuda de Rede refeitas só depois do deploy; OLT com mais de 1000 ONUs (lista parcial avisada, não paginada).

## Consultas à OLT — lote 2a validado: CPU e memória por placa (PR 107)
- Capturas reais supervisionadas (ADR-0032) na MA5608T (slots 0, 1 e 2): `display cpu 0/<slot>` e `display mem 0/<slot>`. A placa de linha responde com uma linha fixa ("Send message … board executing…") antes do valor, só na CPU; a placa de controle responde só com o valor. Fixtures sanitizadas (só percentuais) em `internal/olt/testdata/.../display_{cpu,mem}_0_{0,2}.txt`.
- Go: `go test ./...` do Edge PASS (parsers fechados; falham em: vazio, só a linha fixa, >100 %, sem `%`, duas respostas, texto livre, rótulo trocado, linha fixa repetida ou depois do valor, linha fixa na memória). Python: `test_olt_query.py` + `test_olt_cache.py` 42 passed; `ruff` limpo; hash do catálogo `959fdad3…` igual nos dois lados e vetor de intenção `e3ccc5ca…` atualizado.
- `slot.cpu` e `slot.mem` ficam Validated mas FORA do ROLLOUT: a tela só oferece consultas globais; entram quando houver seletor de slot.
- Remoção dos brutos no Edge: os 10 arquivos de captura (lotes 1 e 2a) foram apagados por nome e a listagem seguinte mostrou só `done.json`; cópias locais também apagadas. Motivo adicional: a pasta de capturas estava cheia (`captures_dir_full` desde 01:17 local) e bloqueava `slot.board` e `pon.ont.summary`.
- NÃO verificado: `slot.board` e `pon.ont.summary` (lote 2b: ainda sem captura); a oferta das consultas por slot na tela.

## Consultas à OLT — fechamento do lote 2 (31/10/2026)
- `slot.cpu` e `slot.mem`: validadas (PR 107). `slot.board`: NÃO validada. A saída de `display board 0/<slot>` de uma placa de linha lista todas as ONTs da placa com serial e descrição de cliente; os dois arquivos de linha foram apagados do Edge, o da placa de controle (47 linhas, sem serial nem ONT, conferido por contagem sem imprimir) também; nenhuma fixture foi criada. Parte da saída crua foi impressa na sessão por erro de procedimento: contenção e regras novas na emenda de 31/10/2026 do ADR-0032 (busca na memória do projeto por trechos dela: sem resultado).
- `pon.ont.summary` na PON da bancada: a única tentativa terminou em `session_error` (33 s) e o marcador `done.json` impede nova tentativa automática; a PON da bancada tem outras ONTs além da de bancada, então a saída teria o mesmo risco. NÃO validada; fica para quando houver necessidade e autorização.
- Modo de captura do Edge: desligado ao final (config sem `capture`); a pasta de capturas ficou só com `done.json`.


## Speed Diagnostics TR-143 — nuvem (PR 1, ADR-0038)
- `tests/test_speed.py`: 77 casos PASS (aritmética DL/UL e bases, parcial/inconclusivo/erro sem figura, formato fechado do relatório com 14 mutações recusadas, catálogo de parâmetros sem URL/IP, flag desligada = 403 e nenhum job/linha, permissão por papel, tela de capacidades, sem evidência de redirecionamento = `redirect_unverified` no pedido e no gate, recusas com 409+código+auditoria sem job vivo, idempotência, `SPEED_EDGE_SUPPORT` desligado = `operation_not_homologated`, caminho completo com Edge falso: envelope sem endereço, resultado calculado, reenvio sem efeito, erro do aparelho ≠ escrita falha, relatório inválido = falha + trava, incerto = `UNKNOWN` + trava, limites 1/ONT·1/PON·2/provedor, vínculo sugerido não conta, grupo download/upload, isolamento por tenant, papel da aplicação sem INSERT em destinos, CHECKs do esquema, CLI do dono).
- Teste de esquema: nenhuma coluna das duas tabelas comporta URL, host, endereço, token, segredo ou payload.
- Regressão: testes de RBAC/catálogo/bancada atualizados só nos conjuntos esperados (novas operações e permissão). Matriz RBAC regenerada.
- NÃO verificado: nenhum teste real em ONT/OLT/ACS (nem previsto neste PR); Edge (PR 2) e UI (PR 3) ainda não existem; homologação real depende de autorização do responsável, nó de teste e janela.
