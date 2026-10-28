# ADR-0007: Eventos: outbox transacional + NATS JetStream

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Decisão herdada do PRD v2.

## Decisão

`enqueue()` grava na mesma transação do estado. Relay (`app.workers.relay`) roda como role `fibercore_worker` (SELECT + UPDATE(published_at) em events_outbox via policy dedicada; nada mais), publica com `Nats-Msg-Id`=id do outbox (dedupe do JetStream) e depois marca publicado. Consumer (`app.events.consumer`) grava ledger `processed_events` na MESMA transação do efeito => exatamente-um efeito; ack só após commit; NAK com atraso; após 5 entregas vai a `fibercore.dlq.*`. Subject `fibercore.events.<tenant>.<tipo>` deve coincidir com o tenant do envelope. NATS sobe no Compose dev sem TLS/ACL (apenas dev).

## Consequências

Teste de restart+duplicidade obrigatório no PR de outbox.
