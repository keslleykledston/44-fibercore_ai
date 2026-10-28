# Implementation status (evidência, não promessa)

Atualizado: 2026-10-27 | Branch: `sprint0/01-foundation` | Estado: **Sprint 0 em andamento (PR 1 de N)**

| Item Sprint 0 | Status | Prova | Pendência |
|---|---|---|---|
| A. Compose + make + Dockerfile + lint | Feito (dev) | `make compose-config`, `make up` → postgres/nats/api healthy | lockfile de deps, imagens por digest |
| B. `/livez` `/readyz` `/version` `/v1/platform/modules` | Feito | pytest + smoke via Compose | probes de módulos futuros |
| C. Auth, tenants, users, roles, service accounts, RLS | Feito (base) | 18 testes PASS contra PostgreSQL 17 real | MFA, refresh, rate-limit, OIDC, CRUD HTTP de admin |
| D. Registry/feature flags, OpenAPI | Parcial | OpenAPI válido (`openapi-spec-validator`); registry com probes reais | flags dinâmicas por tenant; lint Spectral; geração de tipos TS/Py |
| E. Outbox + JetStream producer/consumer | **Não iniciado** (tabela criada) | — | PR seguinte |
| F. Mock Edge / Mock NBI | **Não iniciado** | — | PR seguinte |
| G. SBOM/scan, backup/restore staging | **Não iniciado** (CI com gitleaks definido, **não executado**) | — | PR dedicado |
| H. Wiki/ADRs/contexto | Feito (ADR 0001–0010 Proposed) | `docs/wiki/adr/` | aprovação Codex |
| I. Este arquivo | Feito | — | atualizar a cada PR |

Hardware real, GenieACS real, USP controller: **NOT_CONNECTED / NOT_TESTED**. Codex gate: ver `docs/wiki/reviews/PR-01-review-request.md` (**não executado**).
