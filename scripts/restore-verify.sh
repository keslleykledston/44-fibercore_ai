#!/usr/bin/env bash
# Restaura um backup em um banco DESCARTÁVEL (fibercore_restore_check) e verifica integridade.
# Nunca toca no banco "fibercore". Uso: scripts/restore-verify.sh arquivo.dump
set -euo pipefail
cd "$(dirname "$0")/.."
DUMP="${1:?uso: restore-verify.sh arquivo.dump}"
sha256sum -c "$DUMP.sha256"
COMPOSE=(docker compose --env-file "${ENV_FILE:-.env.dev}" -f infra/compose/compose.yaml)
PSQL=("${COMPOSE[@]}" exec -T postgres psql -U fibercore -v ON_ERROR_STOP=1 -At)
"${PSQL[@]}" -d postgres -c "DROP DATABASE IF EXISTS fibercore_restore_check" -c "CREATE DATABASE fibercore_restore_check"
"${COMPOSE[@]}" exec -T postgres pg_restore -U fibercore -d fibercore_restore_check --no-owner --exit-on-error < "$DUMP"
echo "--- verificação"
"${PSQL[@]}" -d fibercore_restore_check -c "SELECT 'alembic_version=' || version_num FROM alembic_version"
"${PSQL[@]}" -d fibercore_restore_check -c "SELECT 'tabelas_rls_forçada=' || count(*) FROM pg_class WHERE relkind='r' AND relforcerowsecurity AND relnamespace='public'::regnamespace"
for t in tenants users_global tenant_memberships edges audit_log events_outbox; do
  "${PSQL[@]}" -d fibercore_restore_check -c "SELECT '$t=' || count(*) FROM $t"
done
"${PSQL[@]}" -d postgres -c "DROP DATABASE fibercore_restore_check"
echo "restore OK (banco de verificação removido)"
