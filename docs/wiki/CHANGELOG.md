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
