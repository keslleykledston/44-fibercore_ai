# ADR-0009: Compose dev: portas e segredos

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Hosts compartilham portas 8000/8001/8002/18000 com outros projetos.

## Decisão

API em `127.0.0.1:${FIBERCORE_API_PORT:-18420}`. Segredos de dev gerados por `make env-dev` em `.env.dev` (gitignored); `.env` do operador nunca é tocado. Serviço one-shot `migrate` usa role dona; `api-core` usa role runtime. Imagens a fixar por digest antes de piloto.

## Consequências

`make compose-config`, `make up` validados.
