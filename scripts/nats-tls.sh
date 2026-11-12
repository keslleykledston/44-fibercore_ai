#!/usr/bin/env bash
# PKI local do NATS com TLS mútuo (ADR-0042). Gera/rotaciona CA, certificado do servidor e UM certificado de cliente por papel.
# Uso:
#   scripts/nats-tls.sh gen   <dir>            cria CA + servidor + clientes (recusa sobrescrever; <dir> deve estar FORA do repositório ou em build/)
#   scripts/nats-tls.sh issue <dir> <alvo>     reemite o certificado de `server` ou de um papel (relay|consumer) com a CA existente (rotação)
# Variáveis: DAYS (validade do certificado folha, padrão 90), CA_DAYS (padrão 1095), KEY_MODE (modo das chaves privadas, padrão 0600;
#   use 0644 SÓ dentro de <dir> 0700 quando o contêiner roda com outro uid, ex.: 10001 na imagem da API).
# Segredos NUNCA entram no repositório: `*.key`/`*.pem` estão no .gitignore e o script recusa um <dir> rastreável pelo Git.
# A identidade de cada papel é o SAN DNS do certificado (`fibercore-<papel>`), casado no servidor por `verify_and_map` (infra/nats/nats-server.conf).
set -euo pipefail
umask 077
ROLES=(relay consumer)   # só quem fala NATS hoje. API e Edge NÃO têm identidade (ver ADR-0042); um papel novo exige ADR + ACL + linha aqui.
DAYS="${DAYS:-90}"; CA_DAYS="${CA_DAYS:-1095}"; KEY_MODE="${KEY_MODE:-0600}"
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
die() { echo "nats-tls: $*" >&2; exit 1; }

guard_dir() {
  local d; d="$(realpath -m "$1")"   # sem criar nada antes de decidir
  case "$d/" in
    "$REPO/build/"*) ;;                                                      # build/ é ignorado pelo Git
    "$REPO/"*) die "$d está dentro do repositório (fora de build/): chaves nunca no repo";;
  esac
  mkdir -p "$d"; chmod 0700 "$d"; echo "$d"
}

new_key() { openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$1" 2>/dev/null; chmod "$KEY_MODE" "$1"; }

issue_leaf() {  # <dir> <nome do arquivo> <CN> <SAN> <extendedKeyUsage>
  local d="$1" name="$2" cn="$3" san="$4" eku="$5" tmp
  tmp="$(mktemp -d "$d/.issue.XXXXXX")"
  new_key "$tmp/$name.key"
  openssl req -new -key "$tmp/$name.key" -subj "/CN=$cn" -out "$tmp/$name.csr"
  printf 'basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=%s\nsubjectAltName=%s\n' "$eku" "$san" > "$tmp/ext.cnf"
  openssl x509 -req -in "$tmp/$name.csr" -CA "$d/ca.pem" -CAkey "$d/ca.key" -CAcreateserial -CAserial "$d/ca.srl" -days "$DAYS" -sha256 -extfile "$tmp/ext.cnf" -out "$tmp/$name.pem" 2>/dev/null
  chmod 0644 "$tmp/$name.pem"
  mv -f "$tmp/$name.key" "$d/$name.key"; mv -f "$tmp/$name.pem" "$d/$name.pem"   # troca por arquivo: leitor nunca vê meio-arquivo
  rm -rf "$tmp"
  echo "emitido $name.pem (CN=$cn, $DAYS dias)"
}

issue_target() {
  case "$2" in
    server) issue_leaf "$1" server nats "DNS:nats,DNS:localhost,IP:127.0.0.1" serverAuth;;
    *) local r; for r in "${ROLES[@]}"; do [[ "$r" == "$2" ]] && { issue_leaf "$1" "$r" "fibercore-$r" "DNS:fibercore-$r" clientAuth; return; }; done
       die "alvo desconhecido '$2' (use server ou: ${ROLES[*]})";;
  esac
}

case "${1:-}" in
  gen)
    [[ $# -eq 2 ]] || usage
    d="$(guard_dir "$2")"
    [[ ! -e "$d/ca.pem" ]] || die "$d já tem uma CA; use 'issue' para rotacionar (gen não sobrescreve)"
    new_key "$d/ca.key"
    openssl req -x509 -new -key "$d/ca.key" -sha256 -days "$CA_DAYS" -subj "/CN=fibercore-nats-ca" -out "$d/ca.pem"
    chmod 0644 "$d/ca.pem"
    issue_target "$d" server
    for r in "${ROLES[@]}"; do issue_target "$d" "$r"; done
    echo "PKI em $d (ca.key fica só aqui; guarde fora do host de produção quando possível)";;
  issue)
    [[ $# -eq 3 ]] || usage
    d="$(guard_dir "$2")"
    [[ -f "$d/ca.pem" && -f "$d/ca.key" ]] || die "sem CA em $d (rode 'gen')"
    issue_target "$d" "$3";;
  *) usage;;
esac
