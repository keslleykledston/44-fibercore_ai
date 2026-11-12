#!/usr/bin/env bash
# E2E completo: stack limpa -> seed sintético -> Next.js (build de produção) -> Playwright (funcional + a11y + capturas).
# Uso: scripts/e2e.sh [--no-screenshots]
# Isolamento (para rodar ao lado de outra stack): COMPOSE_PROJECT_NAME=meu-projeto (os contêineres, a rede e os volumes ganham esse prefixo e o `down -v` do final só atinge ELE; padrão: o `name` do compose),
# FIBERCORE_API_PORT, FIBERCORE_PROXY_HTTP_PORT, FIBERCORE_PROMETHEUS_PORT, FIBERCORE_GRAFANA_PORT e WEB_PORT (portas), E2E_EDGE_CREDS_FILE (onde gravar a conta de serviço descartável do Edge do seed) e
# E2E_PW_ARGS (argumentos extras do Playwright, ex.: "--project=frota --no-deps"; vazio = tudo, como sempre).
set -euo pipefail
cd "$(dirname "$0")/.."
VENV_PY="${VENV_PY:-.venv/bin/python}"
WEB_PORT="${WEB_PORT:-18490}"
make env-dev >/dev/null
COMPOSE=(docker compose ${COMPOSE_PROJECT_NAME:+-p "$COMPOSE_PROJECT_NAME"} --env-file .env.dev -f infra/compose/compose.yaml)
WEB_PID=""
EDGE_CREDS="${E2E_EDGE_CREDS_FILE:-$(mktemp)}"; export E2E_EDGE_CREDS_FILE="$EDGE_CREDS"   # conta de serviço descartável do seed, para o e2e das credenciais (ADR-0045)
cleanup() { rm -f "$EDGE_CREDS"; [[ -z "$WEB_PID" ]] || kill "$WEB_PID" 2>/dev/null || true; "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT
"${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d --build >/dev/null
for _ in $(seq 60); do curl -fs "http://127.0.0.1:${FIBERCORE_API_PORT:-18420}/livez" >/dev/null 2>&1 && break; sleep 1; done
API_URL="http://127.0.0.1:${FIBERCORE_API_PORT:-18420}" "$VENV_PY" scripts/seed_demo.py >/dev/null
cd apps/web
npm ci --no-audit --no-fund >/dev/null
npx next build >/dev/null
if ss -ltn | grep -q ":$WEB_PORT "; then echo "porta $WEB_PORT já em uso" >&2; exit 1; fi
API_INTERNAL_URL="http://127.0.0.1:${FIBERCORE_API_PORT:-18420}" FIBERCORE_INSECURE_COOKIES=1 ./node_modules/.bin/next start -p "$WEB_PORT" >/dev/null 2>&1 &
WEB_PID=$!
for _ in $(seq 40); do curl -fs "http://127.0.0.1:$WEB_PORT/login" >/dev/null 2>&1 && break; sleep 1; done
export WEB_URL="http://127.0.0.1:$WEB_PORT"
export E2E_API_URL="http://127.0.0.1:${FIBERCORE_API_PORT:-18420}"
if [[ -n "${E2E_PW_ARGS:-}" ]]; then npx playwright test $E2E_PW_ARGS
elif [[ "${1:-}" == "--no-screenshots" ]]; then npx playwright test --project=funcional --project=posteriores --project=consultas --no-deps; else npx playwright test; fi
