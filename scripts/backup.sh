#!/usr/bin/env bash
# Backup lógico do PostgreSQL do Compose dev/staging. Uso: scripts/backup.sh [arquivo.dump]
# Formato custom (-Fc), sem owner/ACL do host. NÃO inclui NATS (reconstruível do outbox via `relay replay`).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-build/backups/fibercore-$(date -u +%Y%m%dT%H%M%SZ).dump}"
mkdir -p "$(dirname "$OUT")"
COMPOSE=(docker compose --env-file "${ENV_FILE:-.env.dev}" -f infra/compose/compose.yaml)
"${COMPOSE[@]}" exec -T postgres pg_dump -U fibercore -d fibercore -Fc --no-owner > "$OUT"
sha256sum "$OUT" > "$OUT.sha256"
test -s "$OUT" || { echo "backup vazio" >&2; exit 1; }
echo "backup: $OUT ($(stat -c %s "$OUT") bytes)"
