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
