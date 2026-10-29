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

