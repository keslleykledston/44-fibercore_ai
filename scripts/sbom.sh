#!/usr/bin/env bash
# Gera SBOM CycloneDX + auditoria de vulnerabilidades das dependências Python (lockfile com hashes).
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="${VENV:-.venv}"
OUT="${OUT:-build/sbom}"
mkdir -p "$OUT"
"$VENV/bin/cyclonedx-py" requirements apps/api/requirements.lock --of JSON -o "$OUT/api-sbom.cdx.json" >/dev/null
"$VENV/bin/pip-audit" -r apps/api/requirements.lock --no-deps --disable-pip --progress-spinner off
echo "SBOM: $OUT/api-sbom.cdx.json"
