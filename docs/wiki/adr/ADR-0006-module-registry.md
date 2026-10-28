# ADR-0006: Registry de módulos com status honesto

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Manifest declara 14 módulos; só 2 têm código.

## Decisão

`/v1/platform/modules` calcula status por probes reais (Postgres, NATS monitor). Módulo sem implementação => `unknown`; flag off => `disabled`; dependência requerida fora => `unhealthy`. Nunca `healthy` por declaração. Vocabulário segue `ModuleHealth` do contrato.

## Consequências

Cada módulo novo entra em `IMPLEMENTED` junto com probe e teste.
