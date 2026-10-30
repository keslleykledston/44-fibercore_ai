#!/usr/bin/env bash
# Retenção diária do histórico de estado das ONUs (`onu_state_events`) no LAB (stack fibercore-prod). Pensado para o cron; sai != 0 em qualquer falha.
# Chama `onu_state_events_prune(keep_days)` como DONO do banco (a função recusa quem não ignora o RLS); mantém, por ONU, o último evento anterior ao corte
# (o estado em que a janela começa). keep_days >= 370: cobre a maior janela de consulta (365 dias). Log: ~/fibercore-backups/retention.log (0600).
#   Variável: FIBERCORE_EVENTS_KEEP_DAYS (padrão 400).
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
DIR="${FIBERCORE_BACKUP_DIR:-$HOME/fibercore-backups}"; KEEP="${FIBERCORE_EVENTS_KEEP_DAYS:-400}"
[[ "$KEEP" =~ ^[0-9]+$ && "$KEEP" -ge 370 ]] || { echo "FIBERCORE_EVENTS_KEEP_DAYS inválido (mínimo 370)" >&2; exit 2; }
mkdir -p -m 700 "$DIR"
exec 9>"$DIR/.retention.lock"; flock -n 9 || exit 0
log() { echo "$(date -Is) $*" >> "$DIR/retention.log"; }
trap 'rc=$?; [[ $rc -eq 0 ]] || log "FALHA rc=$rc"' EXIT
COMPOSE=(docker compose -p fibercore-prod --env-file .env.prod -f infra/compose/compose.yaml)
before=$("${COMPOSE[@]}" exec -T postgres psql -U fibercore -d fibercore -Atc "SELECT count(*) FROM onu_state_events")
removed=$("${COMPOSE[@]}" exec -T postgres psql -U fibercore -d fibercore -Atc "SELECT onu_state_events_prune($KEEP)")
log "OK removidos=$removed de $before (keep_days=$KEEP)"
