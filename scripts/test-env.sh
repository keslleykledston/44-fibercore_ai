#!/usr/bin/env bash
# Sobe/derruba Postgres+NATS descartáveis para testes. Uso: scripts/test-env.sh start|stop|run [args-pytest]
# Portas: TEST_PG_PORT (55432) e TEST_NATS_PORT (54222); use as mesmas em `start` e `run`.
# Dados do Postgres em tmpfs e `rm -fv`: a imagem declara VOLUME e um `docker rm -f` sem -v deixaria um volume anônimo por execução (o disco encheu assim).
# `start` e `stop` são execuções separadas e se acham pelo NOME; por isso só tocam contêiner com o rótulo de posse abaixo. Um contêiner de outro uso com o
# mesmo nome faz o script PARAR com erro, sem remover nada (o `-v` apagaria os volumes dele). Se `start` falhar no meio, desfaz só o que ele criou.
set -euo pipefail
cd "$(dirname "$0")/.."
PGP="${TEST_PG_PORT:-55432}"; NATSP="${TEST_NATS_PORT:-54222}"
export TEST_ADMIN_DATABASE_URL="postgresql://fibercore:test_admin_pw_only@127.0.0.1:$PGP/fibercore_test"
export TEST_NATS_URL="nats://127.0.0.1:$NATSP"
LABEL="fibercore.test-env=1"
PG_ID=""; NATS_ID=""; START_OK=0
owned() { docker ps -aq --filter "name=^/$1\$" --filter "label=$LABEL"; }
anyone() { docker ps -aq --filter "name=^/$1\$"; }
remove_owned() { local n id; for n in "$@"; do id="$(owned "$n")"; [[ -z "$id" ]] || docker rm -fv "$id" >/dev/null 2>&1 || true; done; }
refuse_foreign() { local n; for n in "$@"; do if [[ -n "$(anyone "$n")" && -z "$(owned "$n")" ]]; then echo "contêiner '$n' existe e NÃO é deste script (sem o rótulo $LABEL); recusando mexer" >&2; exit 1; fi; done; }
rollback_start() {
  [[ "$START_OK" -eq 1 ]] && return 0
  if [[ -n "$PG_ID" ]]; then docker rm -fv "$PG_ID" >/dev/null 2>&1 || true; fi
  if [[ -n "$NATS_ID" ]]; then docker rm -fv "$NATS_ID" >/dev/null 2>&1 || true; fi
}
case "${1:-run}" in
  start)
    refuse_foreign fc-test-pg fc-test-nats
    remove_owned fc-test-pg fc-test-nats
    trap rollback_start EXIT
    PG_ID="$(docker run -d --name fc-test-pg --label "$LABEL" --tmpfs /var/lib/postgresql/data -e POSTGRES_USER=fibercore -e POSTGRES_PASSWORD=test_admin_pw_only -e POSTGRES_DB=fibercore_test -p "127.0.0.1:$PGP:5432" postgres:17-alpine)"
    NATS_ID="$(docker run -d --name fc-test-nats --label "$LABEL" -p "127.0.0.1:$NATSP:4222" nats:2.11-alpine -js)"
    until docker exec fc-test-pg pg_isready -U fibercore >/dev/null 2>&1; do sleep 1; done; sleep 2
    START_OK=1 ;;
  stop) refuse_foreign fc-test-pg fc-test-nats; remove_owned fc-test-pg fc-test-nats ;;
  run) shift || true; cd apps/api && "${PYTHON:-python}" -m pytest -q "$@" ;;
esac
