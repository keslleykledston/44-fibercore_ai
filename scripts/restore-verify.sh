#!/usr/bin/env bash
# Restaura um backup em um banco NOVO e descartável e verifica integridade.
# Salvaguardas: nome aleatório único; recusa se já existir; remove SOMENTE o banco que ele mesmo criou
# (também em caso de falha). Nunca toca no banco "fibercore". Uso: scripts/restore-verify.sh arquivo.dump
set -euo pipefail
cd "$(dirname "$0")/.."
DUMP="${1:?uso: restore-verify.sh arquivo.dump}"
[[ -f "$DUMP" ]] || { echo "dump não encontrado: $DUMP" >&2; exit 1; }
sha256sum -c "$DUMP.sha256"
COMPOSE=(docker compose --env-file "${ENV_FILE:-.env.dev}" -f infra/compose/compose.yaml)
PSQL=("${COMPOSE[@]}" exec -T postgres psql -U fibercore -v ON_ERROR_STOP=1 -At)
DB="fc_restore_check_$(openssl rand -hex 6)"
[[ "$DB" =~ ^fc_restore_check_[0-9a-f]{12}$ ]] || { echo "nome inválido" >&2; exit 1; }
EXISTS=$("${PSQL[@]}" -d postgres -c "SELECT 1 FROM pg_database WHERE datname='$DB'")
[[ -z "$EXISTS" ]] || { echo "banco $DB já existe; abortando sem tocar nele" >&2; exit 1; }
"${PSQL[@]}" -d postgres -c "CREATE DATABASE $DB"
cleanup() { "${PSQL[@]}" -d postgres -c "DROP DATABASE IF EXISTS $DB" >/dev/null && echo "banco de verificação $DB removido"; }
trap cleanup EXIT
"${COMPOSE[@]}" exec -T postgres pg_restore -U fibercore -d "$DB" --no-owner --exit-on-error < "$DUMP"
echo "--- verificação ($DB)"
"${PSQL[@]}" -d "$DB" -c "SELECT 'alembic_version=' || version_num FROM alembic_version"
"${PSQL[@]}" -d "$DB" -c "SELECT 'tabelas_rls_forçada=' || count(*) FROM pg_class WHERE relkind='r' AND relforcerowsecurity AND relnamespace='public'::regnamespace"
for t in tenants users_global tenant_memberships edges audit_log events_outbox; do
  "${PSQL[@]}" -d "$DB" -c "SELECT '$t=' || count(*) FROM $t"
done
echo "restore OK"
