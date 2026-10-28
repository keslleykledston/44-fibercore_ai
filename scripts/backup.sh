#!/usr/bin/env bash
# Backup lógico do PostgreSQL do Compose dev/staging. Uso: scripts/backup.sh [arquivo.dump]
# Formato custom (-Fc), sem owner/ACL do host. NÃO inclui NATS (reconstruível do outbox via `relay replay`).
# O dump contém TODOS os dados (PII incluída): arquivos 0600 em diretório 0700, nunca sobrescreve destino.
# Com BACKUP_GPG_RECIPIENT=<chave> o dump em claro NUNCA é publicado: só fica em temporário (removido no exit)
# e o destino recebe apenas <arquivo>.gpg + <arquivo>.sha256 (checksum do claro, usado por restore-verify.sh).
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
OUT="${1:-build/backups/fibercore-$(date -u +%Y%m%dT%H%M%SZ).dump}"
DIR="$(dirname "$OUT")"
mkdir -p -m 700 "$DIR"
[[ ! -e "$OUT" && ! -e "$OUT.gpg" && ! -e "$OUT.sha256" ]] || { echo "destino já existe, recusando sobrescrever: $OUT" >&2; exit 1; }
TMP="$(mktemp "$DIR/.backup.XXXXXX")"; GTMP=""; STMP=""
trap 'rm -f "$TMP" "$GTMP" "$STMP"' EXIT   # remove o claro e temporários em qualquer saída
COMPOSE=(docker compose --env-file "${ENV_FILE:-.env.dev}" -f infra/compose/compose.yaml)
"${COMPOSE[@]}" exec -T postgres pg_dump -U fibercore -d fibercore -Fc --no-owner > "$TMP"
test -s "$TMP" || { echo "backup vazio" >&2; exit 1; }
STMP="$(mktemp "$DIR/.backup.sha.XXXXXX")"
echo "$(sha256sum "$TMP" | cut -d' ' -f1)  $(basename "$OUT")" > "$STMP"
publish() { ln "$1" "$2" || { echo "colisão no destino: $2" >&2; exit 1; }; }   # ln falha se existir (atômico)
if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
  GTMP="$(mktemp "$DIR/.backup.gpg.XXXXXX")"
  gpg --batch --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "$GTMP" "$TMP"
  test -s "$GTMP" || { echo "cifra falhou" >&2; exit 1; }
  publish "$GTMP" "$OUT.gpg"; publish "$STMP" "$OUT.sha256"
  echo "backup cifrado: $OUT.gpg (checksum do claro em $OUT.sha256)"
else
  publish "$TMP" "$OUT"; publish "$STMP" "$OUT.sha256"
  echo "backup: $OUT ($(stat -c %s "$OUT") bytes) — ATENÇÃO: sem cifra; manter só em disco controlado"
fi
