# ADR-0008: GenieACS: apenas NBI read-only via Edge

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Instância existente do cliente; não instalar/migrar Mongo.

## Decisão

Cliente NBI de exemplo mantido em `apps/api/app/integrations` como referência de contrato; uso real só dentro do Edge (Sprint 1). Mock NBI para testes contratuais antes de qualquer acesso real. Credenciais do `.env` local nunca lidas por agentes nem enviadas a MCP/LLM.

## Consequências

Nenhuma chamada a GenieACS real nesta fase.
