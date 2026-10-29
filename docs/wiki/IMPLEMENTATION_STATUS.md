# Implementation status (evidência, não promessa)

Atualizado: 2026-10-27 | Branch: `final/15-handoff` | Estado: **Sprint 0 concluída (PR 1–4 mergeados); Sprint 1 em andamento (PR 5)**

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
| Edge Go (allowlist, NBI read-only, heartbeat/snapshot, fila SQLite) | Feito (PR 6) | `go test ./...` PASS; E2E real: Edge Go → API Compose → /v1/edges online + /v1/cpes (NBI **mock**) |
| Drivers OLT Huawei MA5800 / ZTE C300 (read-only, SSH pin de host key, allowlist de comandos) | Feito (PR 7) como **`identified`**: parsers validados só com fixtures SINTÉTICAS | go test -race PASS; golden Go→API PASS. **Nunca testado em equipamento real** |

## Sprint 2
| Item | Status | Prova |
|---|---|---|
| CSV ERP + clientes + associação ONU/cliente com revisão humana | Feito (PR 8) | 71 testes PASS (LGPD hash, limites, conflito, ambiguidade, idempotência, RBAC, tenant) |
| Incidentes/correlação PON (dedupe, histerese, silêncio≠queda) | Feito (PR 9) | 79 testes PASS |
| UX operacional (Lovable) | Não iniciado | PR 10 |

## Sprint 3 (parcial)
| Item | Status | Prova |
|---|---|---|
| Job gate (máquina de estados CAS, aprovações, TTL, envelope Ed25519, verificação no Edge, nonce persistido) | Feito (PR 10) | pytest 97 + go test -race PASS; golden Python→Go de assinatura |
| Escrita real em rede | **BLOQUEADA** (`HOMOLOGATED_WRITES` vazio no Cloud; `ReadOnlyOps` compilado no Edge) | testes de bloqueio |
| USP adapter / release center / copiloto | **Adiados** (ADR-0015) | — |

## Adendo v2.1 (domínio, design system, ajuda)
| Item | Status | Prova |
|---|---|---|
| Kit v2.1 importado sem sobrescrever arquivos modificados (merge manual de modules.yaml/OpenAPI/Makefile/.env.example) | Feito | `validate_kit.py` PASS (15 módulos), `validate_help.py` PASS (3 artigos `draft`) |
| `/api/v1` + proxy Caddy (profile `public`), rotas internas bloqueadas | Feito (dev, HTTP loopback) | `scripts/test-proxy.sh` 10/10 PASS |
| DNS/TLS/publicação em `fibercore.devops.k3gsolutions.com.br` | **NÃO realizado** (depende de infra e gate) | — |
| Frontend `apps/web` (Next.js 15, BFF HttpOnly, tokens, 5 telas: Visão Geral/Rede/NOC/Módulos/Ajuda), Central de Ajuda, Playwright | Feito (PR 12; W1–W7) | `scripts/e2e.sh` 20/20 PASS (funcional, CSRF, cookie, a11y axe claro/escuro, capturas); 5 How-to `published` com capturas REAIS |
| Telas Assinantes + Operações (W8) | Feito (PR 14) | `scripts/e2e.sh` 27/27 PASS (aprovação com confirmação, ambíguo bloqueado, importação sem eco de valores, escrita bloqueada); 7 How-to published |
| Hardening de publicação (W9): lockout de login feito; MFA, refresh, CSP, HSTS, DNS/TLS | Parcial | pytest 114 (ver TEST_EVIDENCE: verificação final) |
| Proposta UX do Lovable | Solicitada (projeto Lovable criado); **não integrada** — UI atual segue os tokens do design system, revisão visual Lovable pendente | — |
| Adendo v2.2 (FC22-001..018) | **Só planejamento** (PR 34): análise de GAP, conflitos, ADR-0019…0023, contrato reconciliado, backlog integrado. Nenhuma capacidade nova implementada | `python tests/validate_addendum_v22.py` PASS; mutações (adendo alterado, `implemented` sem existir, FC22/AC removidos) reprovadas |
| FC22-002 Capability Registry — fatia mínima (PR 35) | **Parcial implementado** (mecanismo + leitura + UI mínima; registro vazio no LAB) | pytest 202 (7 novos: unknown padrão, perfil exato, escrita nunca liberada, A/B, RBAC, CHECK de evidência, CLI); E2E 41; 5 mutações reprovadas; capturas reais ONU 360 |
| FC22-004 Vínculo ONU↔CPE + Customer Context (PR 37) | **Implementado, flags desligadas por padrão** (ligadas só no tenant demo); sem regra além de `serial_equal`; sem busca por cliente na UI | pytest 220 (10 novos); E2E 42; 7 mutações reprovadas; capturas reais ONU 360 com o card do roteador |
