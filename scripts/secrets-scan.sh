#!/usr/bin/env bash
# Varredura de segredos com gitleaks (container, sem instalar nada no host). Falha se achar algo.
set -euo pipefail
cd "$(dirname "$0")/.."
docker run --rm -v "$PWD:/repo:ro" zricethezav/gitleaks:v8.21.2 detect --source /repo --no-banner --redact --exit-code 1 \
  --log-opts="--all"
