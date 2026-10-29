#!/usr/bin/env bash
# Backup diário do LAB (stack fibercore-prod) com verificação de restauração e retenção. Pensado para o cron; sai != 0 em qualquer falha.
#   Variáveis: FIBERCORE_BACKUP_DIR (padrão ~/fibercore-backups, 0700), FIBERCORE_BACKUP_KEEP (padrão 14), BACKUP_GPG_RECIPIENT (cifra).
# O dump tem TODOS os dados (PII): arquivos 0600. NÃO inclui .env.prod nem a chave do MFA (guardar à parte; sem ela o MFA cadastrado se perde).
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
DIR="${FIBERCORE_BACKUP_DIR:-$HOME/fibercore-backups}"; KEEP="${FIBERCORE_BACKUP_KEEP:-14}"
[[ "$KEEP" =~ ^[0-9]+$ && "$KEEP" -ge 3 ]] || { echo "FIBERCORE_BACKUP_KEEP inválido (mínimo 3)" >&2; exit 2; }
mkdir -p -m 700 "$DIR"
exec 9>"$DIR/.lock"; flock -n 9 || { echo "$(date -Is) backup já em execução; saindo" >> "$DIR/backup.log"; exit 0; }
log() { echo "$(date -Is) $*" >> "$DIR/backup.log"; }
trap 'rc=$?; [[ $rc -eq 0 ]] || log "FALHA rc=$rc"' EXIT
export ENV_FILE=.env.prod COMPOSE_PROJECT=fibercore-prod
OUT="$DIR/fibercore-prod-$(date -u +%Y%m%dT%H%M%SZ).dump"
./scripts/backup.sh "$OUT" >/dev/null
VERIFY="$OUT"; [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]] && VERIFY="$OUT.gpg"
./scripts/restore-verify.sh "$VERIFY" > "$DIR/.last-verify.txt" 2>&1 || { cat "$DIR/.last-verify.txt" >> "$DIR/backup.log"; exit 1; }
grep -q '^restore OK' "$DIR/.last-verify.txt" || { log "verificação sem 'restore OK'"; exit 1; }
# retenção: mantém os KEEP conjuntos mais novos (dump ou .gpg + .sha256); só apaga o que este script produz
mapfile -t OLD < <(ls -1 "$DIR"/fibercore-prod-*.sha256 2>/dev/null | sort | head -n -"$KEEP")
for s in "${OLD[@]}"; do base="${s%.sha256}"; rm -f -- "$s" "$base" "$base.gpg"; done
log "OK $(basename "$VERIFY") $(stat -c %s "$VERIFY") bytes; mantidos: $(ls -1 "$DIR"/fibercore-prod-*.sha256 | wc -l); removidos: ${#OLD[@]}"
