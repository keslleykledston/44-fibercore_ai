#!/usr/bin/env bash
# E2E completo: stack limpa -> seed sintético -> Next.js (build de produção) -> Playwright (funcional + a11y + capturas).
# Uso: scripts/e2e.sh [--no-screenshots]
set -euo pipefail
cd "$(dirname "$0")/.."
VENV_PY="${VENV_PY:-.venv/bin/python}"
WEB_PORT="${WEB_PORT:-18490}"
make env-dev >/dev/null
COMPOSE=(docker compose --env-file .env.dev -f infra/compose/compose.yaml)
WEB_PID=""
cleanup() { [[ -z "$WEB_PID" ]] || kill "$WEB_PID" 2>/dev/null || true; "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
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
if [[ "${1:-}" == "--no-screenshots" ]]; then npx playwright test --project=funcional --project=posteriores --no-deps; else npx playwright test; fi
