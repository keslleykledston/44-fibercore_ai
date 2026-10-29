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
# Dump publicado mas NÃO verificado: guardado (pode ser um backup bom com verificador quebrado), marcado .failed e limitado aos 2 mais novos,
# para falhas repetidas nunca encherem o disco.
prune_failed() {
  mapfile -t F < <(ls -1 "$DIR"/fibercore-prod-????????T??????Z.dump.failed 2>/dev/null | sort | head -n -2)
  for m in "${F[@]}"; do base="${m%.failed}"; rm -f -- "$m" "$base" "$base.gpg" "$base.sha256"; done
}
trap 'rc=$?; if [[ $rc -ne 0 ]]; then log "FALHA rc=$rc"; [[ -e "${OUT:-/nonexistent}" || -e "${OUT:-/nonexistent}.gpg" ]] && : > "$OUT.failed"; fi; prune_failed' EXIT
export ENV_FILE=.env.prod COMPOSE_PROJECT=fibercore-prod
OUT="$DIR/fibercore-prod-$(date -u +%Y%m%dT%H%M%SZ).dump"
[[ -n "${BACKUP_GPG_RECIPIENT:-}" ]] || log "AVISO: backup SEM cifra (BACKUP_GPG_RECIPIENT não definido); manter só neste host, 0600, e NÃO copiar para fora sem cifrar"
./scripts/backup.sh "$OUT" >/dev/null 2>>"$DIR/backup.log" || { log "FALHA no pg_dump/publicação (detalhe acima)"; exit 1; }
VERIFY="$OUT"; [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]] && VERIFY="$OUT.gpg"
./scripts/restore-verify.sh "$VERIFY" > "$DIR/.last-verify.txt" 2>&1 || { cat "$DIR/.last-verify.txt" >> "$DIR/backup.log"; exit 1; }
grep -q '^restore OK' "$DIR/.last-verify.txt" || { log "verificação sem 'restore OK'"; exit 1; }
: > "$OUT.done"   # marcador: só conjuntos que ESTA rotina concluiu e verificou entram na retenção
# retenção: mantém os KEEP conjuntos concluídos mais novos; apaga só <base>, <base>.gpg, <base>.sha256 e <base>.done desses conjuntos
mapfile -t OLD < <(ls -1 "$DIR"/fibercore-prod-????????T??????Z.dump.done 2>/dev/null | sort | head -n -"$KEEP")
for m in "${OLD[@]}"; do base="${m%.done}"; rm -f -- "$m" "$base" "$base.gpg" "$base.sha256"; done
log "OK $(basename "$VERIFY") $(stat -c %s "$VERIFY") bytes; mantidos: $(ls -1 "$DIR"/fibercore-prod-????????T??????Z.dump.done | wc -l); removidos: ${#OLD[@]}"
