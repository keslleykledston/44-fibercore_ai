# ADR-0001: Monorepo e estrutura do repositório

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Kit v2 importado na raiz; `legacy/` preservado intocado; `apps/api`, `agents/edge`, `configs`, `contracts`, `infra`, `docs`.

## Decisão

Monorepo único. Código do starter movido para `apps/api` (git mv). Repo remoto alvo `keslleykledston/120-OLT_SaaS` (ainda sem remote; sem push sem ordem).

## Consequências

Um PR coerente por vertical; Edge Go entra em `agents/edge` na Sprint 1.
