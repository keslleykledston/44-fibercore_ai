# ADR-0007: Eventos: outbox transacional + NATS JetStream

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Decisão herdada do PRD v2.

## Decisão

Tabela `events_outbox` criada (RLS, tenant). Producer/relay e consumer idempotente ficam para o PR seguinte (entrega E da Sprint 0). NATS sobe no Compose dev sem TLS/ACL (apenas dev).

## Consequências

Teste de restart+duplicidade obrigatório no PR de outbox.
