# ADR-0003: Multitenancy: PostgreSQL RLS + role runtime sem privilégios

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Segurança exige defesa em profundidade; não confiar só na aplicação.

## Decisão

`FORCE ROW LEVEL SECURITY` em todas as tabelas de tenant. Contexto via `set_config('app.tenant_id', …, true)` (equivalente a SET LOCAL) dentro de transação, só após validar membership. Role `fibercore_app`: LOGIN, NOSUPERUSER, NOBYPASSRLS, não-dona das tabelas. Sem contexto => zero linhas (fail closed). `audit_log` append-only (somente SELECT/INSERT). Criação de tenants/usuários só via CLI com role dona (`ADMIN_DATABASE_URL`), nunca por HTTP nesta fase.

## Consequências

Testes: isolamento A/B no nível do banco, WITH CHECK bloqueando escrita cruzada, role sem BYPASSRLS, audit imutável. `users_global` não tem RLS (identidade global) e o role runtime lê `password_hash` — risco aceito e registrado em KNOWN_ISSUES; mitigar com função SECURITY DEFINER no futuro.
