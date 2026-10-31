#!/usr/bin/env bash
# Sobe/derruba Postgres+NATS descartáveis para testes. Uso: scripts/test-env.sh start|stop|run [args-pytest]
# Dados do Postgres em tmpfs e `rm -fv`: a imagem declara VOLUME e um `docker rm -f` sem -v deixaria um volume anônimo por execução (o disco encheu assim).
# `start` e `stop` são execuções separadas e se acham pelo NOME; por isso só tocam contêiner com o rótulo de posse abaixo. Um contêiner de outro uso com o
# mesmo nome faz o script PARAR com erro, sem remover nada (o `-v` apagaria os volumes dele).
set -euo pipefail
cd "$(dirname "$0")/.."
export TEST_ADMIN_DATABASE_URL=postgresql://fibercore:test_admin_pw_only@127.0.0.1:55432/fibercore_test
export TEST_NATS_URL=nats://127.0.0.1:54222
LABEL="fibercore.test-env=1"
owned() { docker ps -aq --filter "name=^/$1\$" --filter "label=$LABEL"; }
anyone() { docker ps -aq --filter "name=^/$1\$"; }
remove_owned() { local n id; for n in "$@"; do id="$(owned "$n")"; [[ -z "$id" ]] || docker rm -fv "$id" >/dev/null 2>&1 || true; done; }
refuse_foreign() { local n; for n in "$@"; do if [[ -n "$(anyone "$n")" && -z "$(owned "$n")" ]]; then echo "contêiner '$n' existe e NÃO é deste script (sem o rótulo $LABEL); recusando mexer" >&2; exit 1; fi; done; }
case "${1:-run}" in
  start)
    refuse_foreign fc-test-pg fc-test-nats
    remove_owned fc-test-pg fc-test-nats
    docker run -d --name fc-test-pg --label "$LABEL" --tmpfs /var/lib/postgresql/data -e POSTGRES_USER=fibercore -e POSTGRES_PASSWORD=test_admin_pw_only -e POSTGRES_DB=fibercore_test -p 127.0.0.1:55432:5432 postgres:17-alpine >/dev/null
    docker run -d --name fc-test-nats --label "$LABEL" -p 127.0.0.1:54222:4222 nats:2.11-alpine -js >/dev/null
    until docker exec fc-test-pg pg_isready -U fibercore >/dev/null 2>&1; do sleep 1; done; sleep 2 ;;
  stop) refuse_foreign fc-test-pg fc-test-nats; remove_owned fc-test-pg fc-test-nats ;;
  run) shift || true; cd apps/api && "${PYTHON:-python}" -m pytest -q "$@" ;;
esac
