#!/usr/bin/env bash
# Varredura de segredos com gitleaks (container, sem instalar nada no host). Falha se achar algo.
set -euo pipefail
cd "$(dirname "$0")/.."
docker run --rm -v "$PWD:/repo:ro" zricethezav/gitleaks:v8.21.2@sha256:0e99e8821643ea5b235718642b93bb32486af9c8162c8b8731f7cbdc951a7f46 detect --source /repo --no-banner --redact --exit-code 1 \
  --log-opts="--all"
