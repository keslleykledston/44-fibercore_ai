#!/usr/bin/env python3
"""Interop ADR-0046, passo de dados: liga as flags do tenant do seed_demo (org A) e cria a org B (segunda organização) com Edge e conta de serviço próprios.

Valores de TESTE descartáveis, só na pilha efêmera (COMPOSE_PROJECT_NAME obrigatório: o script recusa o projeto padrão). Uso:
  COMPOSE_PROJECT_NAME=fibercore-interop46 API_URL=... python scripts/interop46/seed_orgs.py <tenant_id_da_org_A> <arquivo_creds_edgeB> <arquivo_estado.json>
Grava (0600) as credenciais da conta de serviço do Edge B e um JSON com os ids; não imprime segredo.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import httpx

PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "")
if not PROJECT or PROJECT in ("fibercore-prod", "fibercore-dev"):
    sys.exit("defina COMPOSE_PROJECT_NAME para a pilha efêmera (nunca fibercore-prod/fibercore-dev)")
API = os.environ.get("API_URL", "http://127.0.0.1:28420")
PW = os.environ.get("DEMO_PASSWORD", "demo-password-123")
COMPOSE = ["docker", "compose", "-p", PROJECT, "--env-file", ".env.dev", "-f", "infra/compose/compose.yaml"]
FLAGS = ("fleet_manager", "fleet_provision", "fleet_secrets")


def cli(*args: str, env: dict | None = None) -> str:
    cmd = [*COMPOSE, "run", "--rm", "-T", "--no-deps", *(sum([["-e", f"{k}={v}"] for k, v in (env or {}).items()], [])), "migrate", "python", "-m", "app.cli", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def main() -> None:
    tenant_a, creds_b, state_path = sys.argv[1], sys.argv[2], sys.argv[3]
    for f in FLAGS:
        cli("feature-set", tenant_a, f, "on")
    out = cli("create-tenant", "Org Interop B (dados fictícios)", "--demo").strip().splitlines()
    tenant_b = out[-1]
    cli("create-user", "admin-b@interop.example.com", "Admin B", "--password-env", "DEMO_PW", env={"DEMO_PW": PW})
    cli("add-member", tenant_b, "admin-b@interop.example.com", "isp_admin")
    for f in FLAGS:
        cli("feature-set", tenant_b, f, "on")
    edge_b = cli("register-edge", tenant_b, "edge-interop-b", "--site", "Site B (teste)").strip().splitlines()[-1]
    sa = cli("create-service-account", tenant_b, "edge-interop-b-agent", "edge_agent", "--edge-id", edge_b)
    cid = next(line.split("=", 1)[1] for line in sa.splitlines() if line.startswith("client_id="))
    secret = next(line.split("=", 1)[1].split()[0] for line in sa.splitlines() if line.startswith("client_secret="))
    fd = os.open(creds_b, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({"client_id": cid, "client_secret": secret}))
    # confere os ids reais pelo login do admin A (o tenant do seed tem um Edge)
    c = httpx.Client(base_url=API, timeout=15)
    tok = c.post("/v1/auth/token", json={"email": "admin@demo.example.com", "password": PW}).json()["access_token"]
    edges_a = c.get("/v1/edges", headers={"Authorization": f"Bearer {tok}"}).json()
    fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({"tenant_a": tenant_a, "edge_a": edges_a[0]["id"], "tenant_b": tenant_b, "edge_b": edge_b, "client_id_b": cid}))
    print(f"tenant_b={tenant_b} edge_b={edge_b} edge_a={edges_a[0]['id']}")


if __name__ == "__main__":
    main()
