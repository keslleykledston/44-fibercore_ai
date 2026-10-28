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
