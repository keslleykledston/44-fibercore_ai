#!/usr/bin/env bash
# Interoperação REAL navegador -> API -> Edge Go do ADR-0046 (OLT gerenciada), em pilha EFÊMERA e PRÓPRIA. Nada aqui toca fibercore-prod nem fibercore-dev.
# Uso:  INTEROP_DIR=/caminho/de/trabalho scripts/interop46/run.sh up | aux-start | aux-stop | test [args do playwright] | down
#   up         pilha compose própria (-p fibercore-interop46), seed (org A) + org B, Edge/sshsink compilados, web de produção, sshsink + proxy + 2 Edges
#   test       Playwright (scripts/interop46/interop46.spec.ts) contra essa pilha; evidências em $INTEROP_DIR/evidence
#   down       derruba TUDO que o `up` criou (compose down -v SÓ do projeto próprio, processos por PID/porta, .env.dev, symlink de node_modules)
# Variáveis: INTEROP_DIR (obrigatória), COMPOSE_PROJECT_NAME (padrão fibercore-interop46; recusa fibercore-prod/dev), VENV_PY, portas INTEROP_API_PORT/INTEROP_PROXY_PORT/INTEROP_WEB_PORT.
# Todos os segredos são de TESTE e descartáveis (.env.dev é gerado por `make env-dev` com valores aleatórios; o .env real nunca é lido).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
: "${INTEROP_DIR:?defina INTEROP_DIR (diretório de trabalho da prova)}"
W="$INTEROP_DIR"
PROJECT="${COMPOSE_PROJECT_NAME:-fibercore-interop46}"
case "$PROJECT" in fibercore-prod|fibercore-dev) echo "recuso o projeto $PROJECT" >&2; exit 2;; esac
API_PORT="${INTEROP_API_PORT:-28420}"; PROXY_PORT="${INTEROP_PROXY_PORT:-28421}"; WEB_PORT="${INTEROP_WEB_PORT:-28490}"
PY="${VENV_PY:-$ROOT/.venv/bin/python}"
SINK_USER="interop-user"; SINK_PASS="interop-test-pass"
export COMPOSE_PROJECT_NAME="$PROJECT" FIBERCORE_API_PORT="$API_PORT" API_URL="http://127.0.0.1:$API_PORT" INTEROP_SINK_USER="$SINK_USER" INTEROP_SINK_PASS="$SINK_PASS"
COMPOSE=(docker compose -p "$PROJECT" --env-file .env.dev -f infra/compose/compose.yaml)
# IPs locais (pontes do docker) usados como "IPs de OLT": escolhidos por não serem loopback e existirem nesta máquina; o sshsink escuta em todos (TCP 22022/22023, UDP 16161 no .22.0.1).
IPS=(172.17.0.1 172.18.0.1 172.19.0.1 172.20.0.1 172.21.0.1 172.22.0.1 172.23.0.1)

aux_stop() {
  for n in sink proxy edgeA edgeB; do
    if [[ -f "$W/$n.pid" ]]; then kill "$(cat "$W/$n.pid")" 2>/dev/null || true; rm -f "$W/$n.pid"; fi
  done
  fuser -k "$PROXY_PORT/tcp" >/dev/null 2>&1 || true
}
web_stop() {
  if [[ -f "$W/web.pid" ]]; then kill "$(cat "$W/web.pid")" 2>/dev/null || true; rm -f "$W/web.pid"; fi
  fuser -k "$WEB_PORT/tcp" >/dev/null 2>&1 || true
}

aux_start() {
  mkdir -p "$W/captured" "$W/evidence"
  printf '%s' "$SINK_PASS" > "$W/sink.pass"; chmod 600 "$W/sink.pass"
  local L=""; for ip in "${IPS[@]}"; do L+="$ip:22022,$ip:22023,"; done; L="${L%,}"
  : > "$W/sink.log"; : > "$W/proxy.log"; echo '{"mode":"pass"}' > "$W/proxy-ctrl.json"
  nohup "$W/bin/sshsink" -listen "$L" -udp 172.22.0.1:16161 -log "$W/sink.log" -fingerprint-file "$W/sink.fp" -host-key-file "$W/sink.key" -user "$SINK_USER" -pass-file "$W/sink.pass" > "$W/sink.out" 2>&1 &
  echo $! > "$W/sink.pid"
  nohup "$PY" scripts/interop46/edgeproxy.py "$PROXY_PORT" "http://127.0.0.1:$API_PORT" "$W/proxy-ctrl.json" "$W/proxy.log" "$W/captured" > "$W/proxy.out" 2>&1 &
  echo $! > "$W/proxy.pid"
  sleep 1
  local HK; HK="$(cat "$W/sink.fp")"
  local S; S="$(cat "$W/state.json")"
  local TA EA TB EB
  TA="$("$PY" -c "import json,sys;print(json.loads(sys.argv[1])['tenant_a'])" "$S")"; EA="$("$PY" -c "import json,sys;print(json.loads(sys.argv[1])['edge_a'])" "$S")"
  TB="$("$PY" -c "import json,sys;print(json.loads(sys.argv[1])['tenant_b'])" "$S")"; EB="$("$PY" -c "import json,sys;print(json.loads(sys.argv[1])['edge_b'])" "$S")"
  # Edge A: 1 OLT estática (172.21.0.1) + política (6 redes /16, portas 22/22022/22023/16161, max 5, só huawei, sem legado). Passa pelo proxy. Edge B: 1 rede (172.19.0.0/16) que o Edge A NÃO libera.
  "$PY" scripts/interop46/mkedge.py "$W/edgeA" "$W/edge1-creds.json" "$EA" "$TA" "http://127.0.0.1:$PROXY_PORT" .env.dev "172.21.0.1:22022" "$HK" 5 \
    172.17.0.0/16,172.18.0.0/16,172.20.0.0/16,172.21.0.0/16,172.22.0.0/16,172.23.0.0/16 22,22022,22023,16161 >/dev/null
  "$PY" scripts/interop46/mkedge.py "$W/edgeB" "$W/edge2-creds.json" "$EB" "$TB" "http://127.0.0.1:$API_PORT" .env.dev - "$HK" 5 172.19.0.0/16 22022 >/dev/null
  for e in A B; do
    ( cd "$W"; nohup "$W/bin/fibercore-edge" -config "$W/edge$e/config.json" >> "$W/edge$e.log" 2>&1 & echo $! > "$W/edge$e.pid" )
  done
}

case "${1:-}" in
  up)
    make env-dev >/dev/null
    mkdir -p "$W/bin" "$W/evidence"
    "${COMPOSE[@]}" up -d --build api-core outbox-relay job-sweeper event-consumer >"$W/up.log" 2>&1
    for _ in $(seq 60); do curl -fs "http://127.0.0.1:$API_PORT/livez" >/dev/null 2>&1 && break; sleep 1; done
    E2E_EDGE_CREDS_FILE="$W/edge1-creds.json" "$PY" scripts/seed_demo.py > "$W/seed.out"
    TENANT_A="$(sed -n 's/^tenant=//p' "$W/seed.out")"
    "$PY" scripts/interop46/seed_orgs.py "$TENANT_A" "$W/edge2-creds.json" "$W/state.json" >/dev/null
    ( cd agents/edge && CGO_ENABLED=0 go build -ldflags "-X main.version=0.9.0-interop46" -o "$W/bin/fibercore-edge" ./cmd/fibercore-edge )
    ( cd scripts/interop46/sshsink && GOFLAGS=-mod=mod GOPROXY=off go build -o "$W/bin/sshsink" . )
    sha256sum "$W/bin/fibercore-edge" | cut -c1-16 > "$W/edge.sha"
    [[ -e apps/web/node_modules ]] || { ln -s "${WEB_NODE_MODULES:-$ROOT/../../../apps/web/node_modules}" apps/web/node_modules; touch "$W/.linked-node-modules"; }
    ( cd apps/web && npx next build >"$W/webbuild.log" 2>&1 )
    ( cd apps/web; API_INTERNAL_URL="http://127.0.0.1:$API_PORT" FIBERCORE_INSECURE_COOKIES=1 nohup ./node_modules/.bin/next start -p "$WEB_PORT" >"$W/web.log" 2>&1 & echo $! > "$W/web.pid" )
    for _ in $(seq 40); do curl -fs "http://127.0.0.1:$WEB_PORT/login" >/dev/null 2>&1 && break; sleep 1; done
    aux_start
    echo "pilha no ar: api :$API_PORT, proxy do Edge A :$PROXY_PORT, web :$WEB_PORT"
    ;;
  aux-start) aux_start ;;
  aux-stop) aux_stop ;;
  test)
    shift
    [[ -e scripts/interop46/node_modules ]] || { ln -s ../../apps/web/node_modules scripts/interop46/node_modules; touch "$W/.linked-spec-node-modules"; }
    cd scripts/interop46
    INTEROP_DIR="$W" INTEROP_API_PORT="$API_PORT" INTEROP_PROXY_PORT="$PROXY_PORT" INTEROP_SINK_USER="$SINK_USER" INTEROP_SINK_PASS="$SINK_PASS" INTEROP_COMPOSE_PROJECT="$PROJECT" \
      WEB_URL="http://127.0.0.1:$WEB_PORT" E2E_API_URL="http://127.0.0.1:$API_PORT" npx playwright test -c playwright.interop.config.ts "$@"
    ;;
  down)
    aux_stop
    web_stop
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
    rm -f .env.dev scripts/interop46/node_modules
    [[ ! -f "$W/.linked-node-modules" ]] || rm -f apps/web/node_modules
    rm -rf apps/web/.next
    echo "derrubado: projeto $PROJECT (contêineres, rede e volumes), processos, .env.dev, links, build do web"
    ;;
  *) echo "uso: $0 up|aux-start|aux-stop|test|down" >&2; exit 2;;
esac
