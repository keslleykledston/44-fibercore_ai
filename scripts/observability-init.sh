#!/usr/bin/env bash
# Cria, FORA do repositório, o env-file do perfil `observability` (ADR-0043): token do /metrics da API e senha do admin do Grafana.
# Uso: scripts/observability-init.sh [ARQUIVO]   (padrão: ~/fibercore-observability/observability.env, diretório 0700, arquivo 0600).
# Não sobrescreve arquivo existente e nunca imprime um valor.
set -euo pipefail
FILE="${1:-$HOME/fibercore-observability/observability.env}"
if [[ -e "$FILE" ]]; then echo "já existe, mantido: $FILE"; exit 0; fi
umask 077
mkdir -p "$(dirname "$FILE")"
chmod 700 "$(dirname "$FILE")"
{
  echo "FIBERCORE_METRICS_TOKEN=$(openssl rand -hex 32)"
  echo "FIBERCORE_GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 16)"
} > "$FILE"
chmod 600 "$FILE"
cat <<EOF
criado (0600): $FILE

Subir o perfil (o MESMO token chega à API e ao Prometheus; a senha só ao Grafana):
  docker compose --env-file <seu .env> --env-file "$FILE" -f infra/compose/compose.yaml --profile observability up -d
Ler a senha do Grafana quando precisar (não é exibida aqui):
  grep '^FIBERCORE_GRAFANA_ADMIN_PASSWORD=' "$FILE"
EOF
