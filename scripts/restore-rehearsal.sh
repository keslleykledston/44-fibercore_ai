#!/usr/bin/env bash
# Ensaio de restauração COMPLETO, num PostgreSQL descartável e isolado (container novo, porta só em loopback, senhas de ensaio). Nunca toca no banco do Compose.
# Vai além de restore-verify.sh: restaura, confere o esquema e o RLS, roda `alembic upgrade head` (tem de ser um no-op se o dump já está no head), SOBE A API sobre o banco restaurado,
# entra com um usuário criado SÓ no banco de ensaio e lê pela API (contagem igual à do banco), e roda a função do sweeper com o role do worker.
# Uso: scripts/restore-rehearsal.sh build/backups/fibercore-AAAAMMDDTHHMMSSZ.dump[.gpg]   (o dump em claro precisa do .sha256 ao lado)
# O dump contém PII: o container e os temporários somem ao fim (também em caso de falha). Chaves de MFA/JWT/PII do ensaio são descartáveis: dado cifrado com as chaves reais NÃO é legível aqui.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
DUMP="${1:?uso: restore-rehearsal.sh arquivo.dump[.gpg]}"
[[ -f "$DUMP" ]] || { echo "dump não encontrado: $DUMP" >&2; exit 1; }
PY="${PYTHON:-$PWD/.venv/bin/python}"
[[ -x "$PY" ]] || { echo "python não encontrado: $PY (defina PYTHON=)" >&2; exit 1; }
WORK="$(mktemp -d)"; CLEAR=""; NAME="fc-restore-rehearsal-$(openssl rand -hex 4)"; UVI_PID=""
cleanup() {
  local rc=$?
  trap - EXIT
  if [[ -n "$UVI_PID" ]]; then   # espera limitada (5 s): se a API não sair, SIGKILL; o container e os temporários SEMPRE são removidos
    kill "$UVI_PID" 2>/dev/null || true
    for _ in $(seq 1 25); do kill -0 "$UVI_PID" 2>/dev/null || break; sleep 0.2; done
    kill -9 "$UVI_PID" 2>/dev/null || true
    wait "$UVI_PID" 2>/dev/null || true
  fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK" || true   # a confirmação abaixo diz se sobrou algo
  # só anuncia a limpeza depois de CONFIRMAR: o container (com o dump restaurado) não pode ficar para trás sem que o operador saiba
  if [[ -n "$(docker ps -a -q -f "name=^${NAME}\$" 2>/dev/null)" ]] || ! docker info >/dev/null 2>&1; then
    echo "ATENÇÃO: não consegui confirmar a remoção do container $NAME (PII do dump): remova à mão com 'docker rm -f $NAME'" >&2
    exit 1
  fi
  [[ -d "$WORK" ]] && { echo "ATENÇÃO: temporários $WORK não foram removidos" >&2; exit 1; }
  echo "container e temporários de ensaio removidos"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP   # sinais também passam pelo cleanup (o EXIT roda no exit); o servidor da API é recolhido antes de apagar o resto
step() { echo; echo "== $*"; }
fail() { echo "FALHOU: $*" >&2; exit 1; }

step "1. integridade do dump"
if [[ "$DUMP" == *.gpg ]]; then
  BASE="${DUMP%.gpg}"; [[ -f "$BASE.sha256" ]] || fail "checksum $BASE.sha256 ausente"
  CLEAR="$WORK/clear.dump"; gpg --batch --yes --decrypt --output "$CLEAR" "$DUMP"
  [[ "$(sha256sum "$CLEAR" | cut -d' ' -f1)" == "$(cut -d' ' -f1 "$BASE.sha256")" ]] || fail "checksum do dump decifrado NÃO confere"
else
  [[ -f "$DUMP.sha256" ]] || fail "checksum $DUMP.sha256 ausente"
  [[ "$(sha256sum "$DUMP" | cut -d' ' -f1)" == "$(cut -d' ' -f1 "$DUMP.sha256")" ]] || fail "checksum do dump NÃO confere"
  CLEAR="$DUMP"
fi
echo "checksum OK ($(stat -c %s "$CLEAR") bytes)"

step "2. PostgreSQL descartável"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
PGPW="$(openssl rand -hex 16)"; APPPW="$(openssl rand -hex 16)"; WRKPW="$(openssl rand -hex 16)"; RBACPW="$(openssl rand -hex 16)"
printf 'POSTGRES_USER=fibercore\nPOSTGRES_PASSWORD=%s\nPOSTGRES_DB=fibercore\n' "$PGPW" > "$WORK/pg.env"   # segredos nunca vão em argv (visível na lista de processos)
docker run -d --name "$NAME" --env-file "$WORK/pg.env" -p "127.0.0.1:$PORT:5432" postgres:17-alpine >/dev/null
until docker exec "$NAME" pg_isready -U fibercore -d fibercore >/dev/null 2>&1; do sleep 1; done
sleep 2   # a imagem reinicia o servidor uma vez depois do initdb
until docker exec "$NAME" pg_isready -U fibercore -d fibercore >/dev/null 2>&1; do sleep 1; done
PSQL=(docker exec -i "$NAME" psql -U fibercore -d fibercore -v ON_ERROR_STOP=1 -At)
"${PSQL[@]}" >/dev/null <<SQL
CREATE ROLE fibercore_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '$APPPW';
CREATE ROLE fibercore_worker LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '$WRKPW';
CREATE ROLE fibercore_rbac LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '$RBACPW';
SQL
echo "container $NAME em 127.0.0.1:$PORT, papéis da aplicação criados antes do restore (eles não vão no dump)"

step "3. restauração (--exit-on-error)"
T0=$(date +%s.%N)
docker exec -i "$NAME" pg_restore -U fibercore -d fibercore --no-owner --exit-on-error < "$CLEAR"
echo "restauração concluída em $(awk "BEGIN{printf \"%.1f\", $(date +%s.%N) - $T0}") s"

step "4. esquema e RLS"
"${PSQL[@]}" -c "SELECT 'alembic_version=' || version_num FROM alembic_version"
FORCED="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_class WHERE relkind='r' AND relforcerowsecurity AND relnamespace='public'::regnamespace")"
UNFORCED="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_class WHERE relkind='r' AND relrowsecurity AND NOT relforcerowsecurity AND relnamespace='public'::regnamespace")"
BYPASS="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'fibercore_%' AND (rolbypassrls OR rolsuper)")"
echo "tabelas com RLS forçado=$FORCED; com RLS ligado e NÃO forçado=$UNFORCED; papéis da aplicação com bypass/superuser=$BYPASS"
[[ "$UNFORCED" == "0" && "$BYPASS" == "0" && "$FORCED" -gt 0 ]] || fail "RLS incompleto no banco restaurado"
for t in tenants users_global tenant_memberships edges olts onus cpes jobs audit_log events_outbox; do
  echo "$t=$("${PSQL[@]}" -c "SELECT count(*) FROM $t")"
done
SEEN="$("${PSQL[@]}" -c "SELECT count(*) FROM tenants")"
NOCTX="$("${PSQL[@]}" <<'SQL'
SET ROLE fibercore_app;
SELECT (SELECT count(*) FROM tenants) + (SELECT count(*) FROM tenant_memberships);
SQL
)"
NOCTX="${NOCTX##*$'\n'}"   # a última linha: a primeira é a etiqueta "SET" do psql
echo "papel da aplicação SEM contexto de tenant enxerga $NOCTX linhas de tenants+memberships (esperado 0; o dono vê $SEEN tenants)"
[[ "$NOCTX" == "0" ]] || fail "o papel da aplicação enxerga dados sem contexto de tenant"

step "5. alembic upgrade head sobre o restaurado (no-op se o dump está no head; senão é um ensaio real do upgrade)"
ADMIN="postgresql://fibercore:$PGPW@127.0.0.1:$PORT/fibercore"
export ADMIN_DATABASE_URL="$ADMIN" APP_DB_PASSWORD="$APPPW" WORKER_DB_PASSWORD="$WRKPW" RBAC_DB_PASSWORD="$RBACPW"
BEFORE="$("${PSQL[@]}" -c "SELECT version_num FROM alembic_version")"
(cd apps/api && "$PY" -m alembic upgrade head 2>&1 | tail -3)
AFTER="$("${PSQL[@]}" -c "SELECT version_num FROM alembic_version")"
HEAD="$(cd apps/api && "$PY" -m alembic heads 2>/dev/null | awk '{print $1}')"
echo "antes=$BEFORE depois=$AFTER head do código=$HEAD"
[[ "$AFTER" == "$HEAD" ]] || fail "o banco restaurado não está no head do código"
[[ "$BEFORE" == "$AFTER" ]] && echo "dump já estava no head: upgrade foi no-op" || echo "AVISO: o dump era mais antigo que o código; o upgrade aplicou $BEFORE → $AFTER"

step "6. API sobre o banco restaurado (usuário de ensaio criado só aqui)"
APIPORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
JWT="$(openssl rand -hex 32)"; PII="$(openssl rand -hex 32)"; MFAK="$("$PY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
SEED="$(openssl rand -base64 32)"
export DATABASE_URL="postgresql://fibercore_app:$APPPW@127.0.0.1:$PORT/fibercore" WORKER_DATABASE_URL="postgresql://fibercore_worker:$WRKPW@127.0.0.1:$PORT/fibercore"
export RBAC_DATABASE_URL="postgresql://fibercore_rbac:$RBACPW@127.0.0.1:$PORT/fibercore" JWT_SECRET="$JWT" PII_HMAC_KEY="$PII" MFA_ENCRYPTION_KEY="$MFAK" JOB_SIGNING_KEY="$SEED"
export MODULE_MANIFEST="$PWD/configs/modules.yaml" NATS_MONITOR_URL="" ENVIRONMENT=rehearsal
LOGIN_PW="$(openssl rand -hex 12)"
TENANT="$("${PSQL[@]}" -c "SELECT t.id FROM tenants t LEFT JOIN olts o ON o.tenant_id = t.id GROUP BY t.id ORDER BY count(o.id) DESC, t.created_at LIMIT 1")"
[[ -n "$TENANT" ]] || fail "o dump não tem nenhum tenant"
OTHER_TENANT="$(cd apps/api && TENANT="$TENANT" LOGIN_PW="$LOGIN_PW" ADMIN="$ADMIN" "$PY" - <<'EOF'
import os
from sqlalchemy import create_engine, text
from app.core.security import hash_secret
e = create_engine(os.environ["ADMIN"].replace("postgresql://", "postgresql+psycopg://", 1))
with e.begin() as c:
    uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES ('rehearsal@example.com','rehearsal',:h) RETURNING id"), {"h": hash_secret(os.environ["LOGIN_PW"])}).scalar()
    c.execute(text("INSERT INTO tenant_memberships VALUES (:t,:u,'noc_n2')"), {"t": os.environ["TENANT"], "u": uid})
    # a SECOND tenant with its own OLT, to which the rehearsal user does NOT belong: the isolation check below needs data that must not come back
    tb = c.execute(text("INSERT INTO tenants(name) VALUES ('rehearsal-other-tenant') RETURNING id")).scalar()
    eb = c.execute(text("INSERT INTO edges(tenant_id, name) VALUES (:t,'rehearsal-edge') RETURNING id"), {"t": tb}).scalar()
    c.execute(text("INSERT INTO olts(tenant_id, edge_id, name, vendor) VALUES (:t,:e,'REHEARSAL-OTHER-TENANT-OLT','huawei')"), {"t": tb, "e": eb})
    print(tb)
EOF
)"
[[ -n "$OTHER_TENANT" ]] || fail "não criou o tenant de ensaio"
(cd apps/api && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$APIPORT" >"$WORK/api.log" 2>&1) &
UVI_PID=$!
for _ in $(seq 1 40); do curl -fsS "http://127.0.0.1:$APIPORT/readyz" >/dev/null 2>&1 && break; sleep 1; done
READY="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$APIPORT/readyz")"
echo "/readyz=$READY"
[[ "$READY" == "200" ]] || { tail -20 "$WORK/api.log" >&2; fail "a API não ficou pronta sobre o banco restaurado"; }
TOKEN="$(printf '{"email":"rehearsal@example.com","password":"%s"}' "$LOGIN_PW" | curl -fsS -X POST "http://127.0.0.1:$APIPORT/v1/auth/token" -H 'content-type: application/json' --data @- | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
printf 'Authorization: Bearer %s\n' "$TOKEN" > "$WORK/auth.hdr"
get() { curl -s -o "$WORK/body.json" -w '%{http_code}' "http://127.0.0.1:$APIPORT$1" -H @"$WORK/auth.hdr" "${@:2}"; }
[[ "$(get /v1/olts)" == "200" ]] || fail "a API não leu /v1/olts com o usuário de ensaio"
API_OLTS="$("$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["items"] if isinstance(d, dict) else d))' "$WORK/body.json")"
DB_OLTS="$("${PSQL[@]}" -c "SELECT count(*) FROM olts WHERE tenant_id = '$TENANT'")"
DB_ALL="$("${PSQL[@]}" -c "SELECT count(*) FROM olts")"
LEAK="$(grep -c REHEARSAL-OTHER-TENANT-OLT "$WORK/body.json" || true)"
echo "OLTs do tenant pela API=$API_OLTS, do tenant no banco=$DB_OLTS, de todos os tenants no banco=$DB_ALL; linhas do outro tenant na resposta=$LEAK"
[[ "$API_OLTS" == "$DB_OLTS" && "$DB_ALL" -gt "$DB_OLTS" && "$LEAK" == "0" ]] || fail "a API não isolou as OLTs do tenant (ou o banco não tem dado de outro tenant para provar isso)"
OTHER="$(get /v1/olts -H "X-Workspace-ID: $OTHER_TENANT")"
LEAK2="$(grep -c REHEARSAL-OTHER-TENANT-OLT "$WORK/body.json" || true)"
echo "tenant existente a que o usuário NÃO pertence -> HTTP $OTHER, linhas dele na resposta=$LEAK2 (esperado 403/404 e 0)"
[[ ( "$OTHER" == "403" || "$OTHER" == "404" ) && "$LEAK2" == "0" ]] || fail "a API entregou dado de um tenant a que o usuário não pertence"

step "7. sweeper com o papel do worker"
(cd apps/api && "$PY" -c "
import os
from app.core.db import make_engine
from app.workers import sweeper
print('sweep_once =', sweeper.sweep_once(make_engine(os.environ['WORKER_DATABASE_URL'])))")

echo; echo "ENSAIO DE RESTAURAÇÃO: PASS"
