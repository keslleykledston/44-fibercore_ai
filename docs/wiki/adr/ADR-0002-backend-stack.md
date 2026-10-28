# ADR-0002: Backend: FastAPI + SQLAlchemy Core + Alembic

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Stack definida no PRD v2. ORM completo adiciona complexidade sem ganho na Sprint 0.

## Decisão

Python 3.12, FastAPI síncrono, SQLAlchemy 2 (Core/`text`) + psycopg3, migrations Alembic em SQL explícito (RLS/grants não são modeláveis por ORM). Revisar ORM quando houver domínio rico.

## Consequências

Migrations idempotentes onde viável; testes rodam `alembic upgrade head` em banco limpo.
