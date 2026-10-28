# Next Actions

1. `git status`, inspect repo. Do not overwrite existing code without inventory.
2. `python tests/validate_kit.py` and `docker compose -f infra/compose/compose.yaml config` (if docker available).
3. Create Sprint 0 ADRs and authenticate multi-tenant with PostgreSQL RLS tests.
4. Implement real module health probes and secure API endpoints before deployment outside local dev.
5. Record outcomes/tests in wiki and send first PR to Codex supervision.
