#!/usr/bin/env bash
# Backup lógico do PostgreSQL do Compose dev/staging. Uso: scripts/backup.sh [arquivo.dump]
# Formato custom (-Fc), sem owner/ACL do host. NÃO inclui NATS (reconstruível do outbox via `relay replay`).
# O dump contém TODOS os dados (PII incluída): arquivo 0600 em diretório 0700.
# Para sair do ambiente controlado, cifre: BACKUP_GPG_RECIPIENT=<chave> scripts/backup.sh  (gera .gpg e remove o claro).
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
OUT="${1:-build/backups/fibercore-$(date -u +%Y%m%dT%H%M%SZ).dump}"
mkdir -p -m 700 "$(dirname "$OUT")"
[[ ! -e "$OUT" && ! -e "$OUT.gpg" && ! -e "$OUT.sha256" ]] || { echo "destino já existe, recusando sobrescrever: $OUT" >&2; exit 1; }
TMP="$(mktemp "$(dirname "$OUT")/.backup.XXXXXX")"   # 0600; mesmo diretório => mv atômico
trap 'rm -f "$TMP"' EXIT
COMPOSE=(docker compose --env-file "${ENV_FILE:-.env.dev}" -f infra/compose/compose.yaml)
"${COMPOSE[@]}" exec -T postgres pg_dump -U fibercore -d fibercore -Fc --no-owner > "$TMP"
test -s "$TMP" || { echo "backup vazio" >&2; exit 1; }
chmod 600 "$TMP"
ln "$TMP" "$OUT" || { echo "colisão: destino criado por outra execução: $OUT" >&2; exit 1; }  # ln falha se existir (atômico)
rm -f "$TMP"
sha256sum "$OUT" > "$OUT.sha256"
if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
  GTMP="$(mktemp "$(dirname "$OUT")/.backup.gpg.XXXXXX")"
  trap 'rm -f "$TMP" "$GTMP"' EXIT
  gpg --batch --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "$GTMP" "$OUT"
  ln "$GTMP" "$OUT.gpg" || { echo "colisão no destino cifrado: $OUT.gpg" >&2; exit 1; }
  rm -f "$GTMP"
  shred -u "$OUT" 2>/dev/null || rm -f "$OUT"
  echo "backup cifrado: $OUT.gpg (checksum do claro em $OUT.sha256)"
else
  echo "backup: $OUT ($(stat -c %s "$OUT") bytes) — ATENÇÃO: sem cifra; manter só em disco controlado"
fi
