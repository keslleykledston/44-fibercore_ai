# Plano de deploy (Compose piloto) — sem promessa de zero downtime

Estado: **dev/lab**. Nada aqui autoriza produção; ver gates em `CLAUDE.md`/PRD.

## Pré-requisitos
1. `make env-dev` (dev) ou segredos via Docker secrets/secret manager (staging/piloto). `.env` do operador nunca é usado.
2. Imagens fixadas por **digest** (hoje por tag — pendência antes do piloto). Dependências Python com hashes em `apps/api/requirements.lock` (`pip-compile --generate-hashes`).
3. `scripts/sbom.sh` (SBOM CycloneDX + pip-audit) e `scripts/secrets-scan.sh` (gitleaks) limpos; scan de imagem (trivy) sem HIGH/CRITICAL corrigível.

## Sequência
1. `scripts/backup.sh` → `scripts/restore-verify.sh <dump>` (prova de restore em banco descartável).
2. `docker compose up -d --build` — `migrate` roda `alembic upgrade head` (one-shot) antes de `api-core`, `outbox-relay`, `event-consumer`.
3. Verificar: `/livez`, `/readyz`, `/v1/platform/modules` (autenticado), logs do relay.
4. Smoke funcional: login, `/v1/tenant`, heartbeat de Edge de teste.

## Rollback
- Código: redeploy da imagem anterior (tag/digest anterior). Migrations são aditivas; `alembic downgrade` testado para 0004→0003 (remove contas `edge_agent`). Antes de qualquer downgrade: backup.
- Dados: restaurar dump em banco novo, apontar `DATABASE_URL`, validar com `restore-verify.sh`.
- Eventos: perda do NATS é recuperável: `python -m app.workers.relay replay <ISO-ts> [tenant]` (consumidores idempotentes).

## Limites assumidos
- Compose não garante rolling update nem auto-recuperação total; há janela de indisponibilidade da API durante recreate.
- NATS dev sem TLS/ACL. Postgres sem HA. Sem métricas/alertas ainda (Sprint 1+: Prometheus/Grafana).
- K3s/HA somente após ensaio e necessidade comprovada (ADR futuro).
