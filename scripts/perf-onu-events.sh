#!/usr/bin/env bash
# Medição de /v1/onus/unstable com volume: Postgres DESCARTÁVEL (porta PERF_PG_PORT, padrão 55442), nada toca o LAB.
# Uso: N_ONU=30000 EV_PER=40 scripts/perf-onu-events.sh   (cria um banco descartável com nome único, migra, gera N_ONU ONUs x EV_PER eventos, mede e REMOVE o que criou ao terminar)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
N_ONU=${N_ONU:-30000}; EV_PER=${EV_PER:-40}
NAME="fc-perf-pg-$$"   # unique per run, labelled: only the container THIS run created is ever removed
PORT=${PERF_PG_PORT:-55442}
if ss -ltn 2>/dev/null | grep -q ":$PORT "; then echo "porta $PORT ocupada (PERF_PG_PORT para outra)" >&2; exit 1; fi
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$NAME" --label fibercore.perf=1 -e POSTGRES_USER=fibercore -e POSTGRES_PASSWORD=perf_admin_pw_only -e POSTGRES_DB=fibercore_perf -p 127.0.0.1:$PORT:5432 postgres:17-alpine >/dev/null
until docker exec "$NAME" pg_isready -U fibercore >/dev/null 2>&1; do sleep 1; done; sleep 2
cd $ROOT/apps/api
ADMIN=postgresql://fibercore:perf_admin_pw_only@127.0.0.1:$PORT/fibercore_perf
APP=perf_app_pw_0123456789abc
ADMIN_DATABASE_URL=$ADMIN APP_DB_PASSWORD=$APP WORKER_DB_PASSWORD=perf_worker_pw_0123456789 RBAC_DB_PASSWORD=perf_rbac_pw_0123456789a $ROOT/.venv/bin/python -m alembic upgrade head >/dev/null 2>&1
docker exec -i "$NAME" psql -U fibercore -d fibercore_perf -v ON_ERROR_STOP=1 -q <<SQL
INSERT INTO tenants(id, name) VALUES ('00000000-0000-0000-0000-0000000000a1', 'perf');
INSERT INTO edges(tenant_id, id, name) VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000e1', 'e1');
INSERT INTO olts(tenant_id, id, edge_id, name, vendor) VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000e1', 'o1', 'huawei');
SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-0000000000a1', false);
INSERT INTO onus(tenant_id, olt_id, serial, status, observed_at)
  SELECT '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b1', 'HWTC' || lpad(g::text, 8, '0'), 'online', now() - interval '410 days' FROM generate_series(1, $N_ONU) g;
-- $EV_PER alternating changes per ONU over the last 400 days, in order (seq follows the order of production)
INSERT INTO onu_state_events(tenant_id, onu_id, olt_id, serial, from_status, to_status, at)
  SELECT o.tenant_id, o.id, o.olt_id, o.serial, CASE WHEN i % 2 = 1 THEN 'online' ELSE 'offline' END, CASE WHEN i % 2 = 1 THEN 'offline' ELSE 'online' END,
         now() - interval '400 days' + (i * 400.0 / $EV_PER) * interval '1 day' - (random() * 0.5) * interval '1 day' * 0
    FROM onus o, generate_series(1, $EV_PER) i ORDER BY o.id, i;
ANALYZE;
SELECT 'onus', count(*) FROM onus UNION ALL SELECT 'events', count(*) FROM onu_state_events;
SQL
$ROOT/.venv/bin/python "$ROOT/scripts/perf_onu_events.py"
