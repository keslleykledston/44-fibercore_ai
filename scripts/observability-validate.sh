#!/usr/bin/env bash
# Valida a configuração do Prometheus com o promtool (config, regras e testes unitários das regras). ADR-0043.
# Usa `promtool` do PATH; senão roda o do MESMO contêiner fixado no compose (docker run --rm, só leitura, sem rede). Não toca em nenhum contêiner existente.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="infra/observability/prometheus"
if command -v promtool >/dev/null 2>&1; then
  RUN=(promtool); CFG="$DIR/prometheus.yml"; RULES="$DIR/rules/*.yml"; TESTS="$DIR/tests/*.yml"
  FAKE="$(mktemp)"; trap 'rm -f "$FAKE"' EXIT
  echo "promtool local não consegue ver /run/secrets: validando a config com uma cópia que aponta para um arquivo vazio"
  CFGTMP="$(mktemp --suffix=.yml)"; trap 'rm -f "$FAKE" "$CFGTMP"' EXIT
  sed "s#/run/secrets/fibercore_metrics_token#$FAKE#; s#/etc/prometheus/rules/#$PWD/$DIR/rules/#" "$DIR/prometheus.yml" > "$CFGTMP"; CFG="$CFGTMP"
else
  FAKE="$(mktemp)"; trap 'rm -f "$FAKE"' EXIT
  RUN=(docker run --rm --network none --entrypoint promtool -v "$PWD/$DIR:/etc/prometheus:ro" -v "$FAKE:/run/secrets/fibercore_metrics_token:ro" prom/prometheus:v3.15.1@sha256:fa3302279710be2f21a8301ec17a8b4f2301fd829bd113839b3b6b02b6f191a2)   # literal: o verificador de digests recusa $VAR; deve ser o mesmo do compose
  CFG="/etc/prometheus/prometheus.yml"; RULES="/etc/prometheus/rules/fibercore.rules.yml"; TESTS="/etc/prometheus/tests/fibercore.rules.test.yml"
fi
"${RUN[@]}" check config "$CFG"
# shellcheck disable=SC2086
"${RUN[@]}" check rules $RULES
# shellcheck disable=SC2086
"${RUN[@]}" test rules $TESTS
echo "observability-validate: OK"
