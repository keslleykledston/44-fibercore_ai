#!/usr/bin/env bash
# Sobe/derruba Postgres+NATS descartáveis para testes. Uso: scripts/test-env.sh start|stop|run [args-pytest]
set -euo pipefail
cd "$(dirname "$0")/.."
export TEST_ADMIN_DATABASE_URL=postgresql://fibercore:test_admin_pw_only@127.0.0.1:55432/fibercore_test
export TEST_NATS_URL=nats://127.0.0.1:54222
case "${1:-run}" in
  start)
    docker rm -f fc-test-pg fc-test-nats >/dev/null 2>&1 || true
    docker run -d --name fc-test-pg -e POSTGRES_USER=fibercore -e POSTGRES_PASSWORD=test_admin_pw_only -e POSTGRES_DB=fibercore_test -p 127.0.0.1:55432:5432 postgres:17-alpine >/dev/null
    docker run -d --name fc-test-nats -p 127.0.0.1:54222:4222 nats:2.11-alpine -js >/dev/null
    until docker exec fc-test-pg pg_isready -U fibercore >/dev/null 2>&1; do sleep 1; done; sleep 2 ;;
  stop) docker rm -f fc-test-pg fc-test-nats >/dev/null 2>&1 || true ;;
  run) shift || true; cd apps/api && "${PYTHON:-python}" -m pytest -q "$@" ;;
esac
