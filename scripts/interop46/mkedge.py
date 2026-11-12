#!/usr/bin/env python3
"""Interop ADR-0046: monta o diretório de um Edge de TESTE (config.json 0600, segredo da conta de serviço, diretórios 0700) para o binário Go real.

Uso: python mkedge.py <dir> <creds_json> <edge_id> <tenant_id> <gateway_url> <job_signing_key_env_file> <static_ip:porta|-> <host_key_sha256_do_sink> <max_olts> <allowed_cidrs,..> <allowed_ports,..>
A chave pública dos jobs é DERIVADA da semente (FIBERCORE_JOB_SIGNING_KEY do .env.dev da pilha efêmera, lido sem ecoar). Valores de teste; nada é impresso além do caminho do config.
"""
from __future__ import annotations

import base64
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def job_public_key(env_file: str) -> str:
    seed = next(line.split("=", 1)[1].strip() for line in open(env_file) if line.startswith("FIBERCORE_JOB_SIGNING_KEY="))
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(seed))
    return base64.b64encode(priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def write(path: str, data: str, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as fh:
        fh.write(data)


def main() -> None:
    d, creds, edge_id, tenant_id, gw, envf, static, hk, max_olts, cidrs, ports = sys.argv[1:12]
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    managed = os.path.join(d, "managed")
    os.makedirs(managed, mode=0o700, exist_ok=True)
    os.chmod(managed, 0o700)
    c = json.load(open(creds))
    write(os.path.join(d, "gw.secret"), c["client_secret"])
    write(os.path.join(d, "static-olt.secret"), os.environ.get("INTEROP_SINK_PASS", "interop-test-pass"))
    cfg: dict = {
        "gateway_url": gw, "allow_insecure_dev": True, "edge_id": edge_id, "tenant_id": tenant_id, "client_id": c["client_id"],
        "secret_file": os.path.join(d, "gw.secret"), "connector_id": "interop46", "queue_path": os.path.join(d, "q", "queue.db"),
        "heartbeat_seconds": 30, "collect_seconds": 30, "jobs_enabled": True, "job_public_key": job_public_key(envf),
        "olt_secrets": {"seal_key_file": os.path.join(d, "seal", "seal-key.json"), "applied_file": os.path.join(d, "olt-secrets-applied.json"), "poll_seconds": 15},
        "managed_olts": {"state_dir": managed, "allowed_cidrs": cidrs.split(","), "allowed_ports": [int(p) for p in ports.split(",")], "max_olts": int(max_olts),
                         "allow_legacy_ssh": False, "allowed_vendors": ["huawei"], "pon_ports": ["0/1/0"]},
        "olts": [], "allowlist": [],
    }
    if static != "-":
        cfg["olts"].append({"name": "OLT-ESTATICA-01", "vendor": "huawei", "address": static, "username": os.environ.get("INTEROP_SINK_USER", "interop-user"),
                            "secret_file": os.path.join(d, "static-olt.secret"), "host_key_sha256": hk, "pon_ports": ["0/1/0"]})
        cfg["allowlist"].append(static)
    os.makedirs(os.path.join(d, "q"), mode=0o700, exist_ok=True)
    write(os.path.join(d, "config.json"), json.dumps(cfg, indent=1))
    print(os.path.join(d, "config.json"))


if __name__ == "__main__":
    main()
