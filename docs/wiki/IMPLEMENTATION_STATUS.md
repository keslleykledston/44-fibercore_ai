# Implementation status (evidência, não promessa)

Atualizado: 2026-10-27 | Branch: `sprint1/05-inventory-ingestion` | Estado: **Sprint 0 concluída (PR 1–4 mergeados); Sprint 1 em andamento (PR 5)**

| Item Sprint 0 | Status | Prova | Pendência |
|---|---|---|---|
| A. Compose + make + Dockerfile + lint | Feito (dev) | `make compose-config`, `make up` → postgres/nats/api healthy | lockfile de deps, imagens por digest |
| B. `/livez` `/readyz` `/version` `/v1/platform/modules` | Feito | pytest + smoke via Compose | probes de módulos futuros |
| C. Auth, tenants, users, roles, service accounts, RLS | Feito (base) | 18 testes PASS contra PostgreSQL 17 real | MFA, refresh, rate-limit, OIDC, CRUD HTTP de admin |
| D. Registry/feature flags, OpenAPI | Parcial | OpenAPI válido (`openapi-spec-validator`); registry com probes reais | flags dinâmicas por tenant; lint Spectral; geração de tipos TS/Py |
| E. Outbox + JetStream producer/consumer | Feito (PR 2) | 26 testes PASS incl. crash/restart, dedupe por Msg-Id, ledger idempotente, DLQ; E2E em Compose | TLS/ACL do NATS (produção); DLQ replay tool |
| F. Mock Edge / Mock NBI / contrato de stream / segredos | Feito (PR 3) | `tools/mocks`, `contracts/edge-frame.schema.json`, `EDGE_GATEWAY_CONTRACT.md`, ADR-0011; 38 testes PASS | mTLS real e Gateway = Sprint 1 |
| G. SBOM/scan, backup/restore, plano de deploy | Feito (PR 4) | sbom+pip-audit (0 vulns), gitleaks (0 leaks), trivy imagem (0 HIGH/CRIT), backup→restore verificado | digest das imagens; CI remoto ainda não executado (sem Actions run) |
| H. Wiki/ADRs/contexto | Feito (ADR 0001–0010 Proposed) | `docs/wiki/adr/` | aprovação Codex |
| I. Este arquivo | Feito | — | atualizar a cada PR |

Hardware real, GenieACS real, USP controller: **NOT_CONNECTED / NOT_TESTED**. Codex gate: ver `docs/wiki/reviews/PR-01-review-request.md` (**não executado**).

Edge-fleet: registro via CLI, `POST /v1/edge/heartbeat` (bearer edge_agent, interino), `GET /v1/edges` com status calculado (stale => offline).

## Sprint 1
| Item | Status | Prova |
|---|---|---|
| Schema inventário + ingestão snapshots + leituras com frescor | Feito (PR 5) | 54 testes PASS (RLS, anti-hijack, out-of-order, stale≠offline, binding conflict, outbox) |
| Edge Go (allowlist, NBI read-only, heartbeat/snapshot) | Não iniciado | PR 6 |
| Drivers OLT Huawei MA5800 / ZTE (fixtures) | Não iniciado | PR 7 |
