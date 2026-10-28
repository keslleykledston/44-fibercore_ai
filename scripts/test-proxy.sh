#!/usr/bin/env bash
# Teste E2E do proxy: /api/v1/* -> /v1/* (strip só de /api), rotas internas bloqueadas, nada além do proxy publicado.
set -euo pipefail
cd "$(dirname "$0")/.."
make env-dev >/dev/null
COMPOSE=(docker compose --env-file .env.dev -f infra/compose/compose.yaml --profile public)
PORT="${FIBERCORE_PROXY_HTTP_PORT:-18480}"
trap '"${COMPOSE[@]}" down -v >/dev/null 2>&1 || true' EXIT
"${COMPOSE[@]}" up -d --build postgres nats migrate api-core proxy >/dev/null
for _ in $(seq 40); do curl -fs "http://127.0.0.1:$PORT/api/v1/auth/me" -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q 401 && break; sleep 1; done
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
fail=0
check() { [[ "$2" == "$3" ]] && echo "PASS $1 ($2)" || { echo "FAIL $1: got $2 want $3"; fail=1; }; }
check "api via proxy exige auth (401)"           "$(code "http://127.0.0.1:$PORT/api/v1/auth/me")" 401
check "login inválido via proxy (401)"            "$(code -X POST -H 'content-type: application/json' -d '{"email":"x@example.com","password":"x"}' "http://127.0.0.1:$PORT/api/v1/auth/token")" 401
check "/api/v1 sem rota => 404 da API"            "$(code "http://127.0.0.1:$PORT/api/v1/nao-existe")" 404
check "prefixo /api removido (v1 direto no proxy não é API)" "$(code "http://127.0.0.1:$PORT/v1/auth/me")" 502
for p in /livez /readyz /metrics /internal/x /docs /openapi.json; do check "interno bloqueado $p" "$(code "http://127.0.0.1:$PORT$p")" 404; done
echo "--- portas publicadas:"; docker ps --filter "name=fibercore-dev" --format '{{.Names}} {{.Ports}}' | grep -E '0\.0\.0\.0|\[::\]' && { echo "FAIL: porta pública inesperada"; fail=1; } || echo "nenhuma em 0.0.0.0 (apenas 127.0.0.1)"
exit $fail
