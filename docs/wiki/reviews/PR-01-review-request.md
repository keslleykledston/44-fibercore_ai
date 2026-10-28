# Review request — Sprint 0 PR 1 (para Codex, read-only)

Escopo: `git diff main...sprint0/01-foundation` (2 commits + este). Prompt: `prompts/02_CODEX_SUPERVISOR.md`.

Focar em: (1) RLS/policies e grants em `apps/api/alembic/versions/0001_*.py`; (2) `apps/api/app/api/deps.py` (derivação de tenant/role); (3) JWT em `app/core/security.py`; (4) vazamento de segredos; (5) divergências com `contracts/fibercore-v2.openapi.yaml`.

Evidência: `docs/wiki/TEST_EVIDENCE.md`. ADRs 0001–0010 em `docs/wiki/adr/` (Proposed).
Status do gate: **CODEX_PLUGIN_NOT_EXECUTED** — nenhuma revisão feita até aqui.

## Resultado Codex (adversarial-review, 2026-10-27)
Rodada 1: needs-attention — [critical] role preexistente não endurecido; [medium] OpenAPI sem X-Workspace-ID em /platform/modules e /platform/versions sem rota. Ambos corrigidos (ALTER ROLE explícito + checagem de membership/ownership; rota /v1/platform/versions; teste `test_zz_migration.py`).

## PR 2 (outbox/JetStream) — Codex
R1 [high] retenção 7d → corrigido (max_age=0 + replay). R2 [high] replay dentro da janela de dedupe → `replay_gen`/novo Nats-Msg-Id. R3 [high] ensure_streams não idempotente → create-or-update. R4 [high] restart zerava max_bytes → limites preservados. R5 [high] "STREAM_MAX_AGE_S em ns" → **falso positivo**, refutado por teste que lê o JSON bruto do servidor (`"max_age":3600000000000` para 3600 s).
