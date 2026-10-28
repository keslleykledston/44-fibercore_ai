# Review request — Sprint 0 PR 1 (para Codex, read-only)

Escopo: `git diff main...sprint0/01-foundation` (2 commits + este). Prompt: `prompts/02_CODEX_SUPERVISOR.md`.

Focar em: (1) RLS/policies e grants em `apps/api/alembic/versions/0001_*.py`; (2) `apps/api/app/api/deps.py` (derivação de tenant/role); (3) JWT em `app/core/security.py`; (4) vazamento de segredos; (5) divergências com `contracts/fibercore-v2.openapi.yaml`.

Evidência: `docs/wiki/TEST_EVIDENCE.md`. ADRs 0001–0010 em `docs/wiki/adr/` (Proposed).
Status do gate: **CODEX_PLUGIN_NOT_EXECUTED** — nenhuma revisão feita até aqui.
