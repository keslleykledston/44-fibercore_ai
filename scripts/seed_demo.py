#!/usr/bin/env python3
"""Seed SINTÉTICO para E2E/screenshots: tenant "ISP Demo", usuário admin, edge, OLTs/ONUs/CPEs fictícios, 1 incidente em massa.

Requer a stack Compose no ar (API em API_URL). Nada aqui é dado real: seriais/nomes são inventados.
Uso: python scripts/seed_demo.py  -> imprime apenas e-mail/senha DEMO (descartáveis, só para o ambiente de teste).
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime

import httpx

API = os.environ.get("API_URL", "http://127.0.0.1:18420")
PW = os.environ.get("DEMO_PASSWORD", "demo-password-123")
EMAIL = "admin@demo.example.com"
COMPOSE = ["docker", "compose", "--env-file", ".env.dev", "-f", "infra/compose/compose.yaml"]


def cli(*args: str, env: dict | None = None) -> str:
    cmd = [*COMPOSE, "run", "--rm", "-T", "--no-deps", *(sum([["-e", f"{k}={v}"] for k, v in (env or {}).items()], [])),
           "migrate", "python", "-m", "app.cli", *args]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip().splitlines()
    return out[-1] if out else ""


def main() -> None:
    tenant = cli("create-tenant", "ISP Demo (dados fictícios)")
    cli("create-user", EMAIL, "Admin Demo", "--password-env", "DEMO_PW", env={"DEMO_PW": PW})
    cli("add-member", tenant, EMAIL, "isp_admin")
    edge = cli("register-edge", tenant, "edge-demo", "--site", "POP Central (demo)")
    sa = subprocess.run([*COMPOSE, "run", "--rm", "-T", "--no-deps", "migrate", "python", "-m", "app.cli",
                         "create-service-account", tenant, "edge-demo-agent", "edge_agent", "--edge-id", edge],
                        check=True, capture_output=True, text=True).stdout
    cid = next(line.split("=", 1)[1] for line in sa.splitlines() if line.startswith("client_id="))
    secret = next(line.split("=", 1)[1].split()[0] for line in sa.splitlines() if line.startswith("client_secret="))

    c = httpx.Client(base_url=API, timeout=15)
    tok = c.post("/v1/auth/service-token", json={"client_id": cid, "client_secret": secret}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    now = datetime.now(UTC).isoformat()
    assert c.post("/v1/edge/heartbeat", headers=h, json={"edge_id": edge, "tenant_id": tenant, "version": "0.1.0-demo", "sent_at": now}).status_code == 204

    def onus(prefix: str, n: int, status: str, pon: str, rx: float | None = -22.0):
        return [{"serial": f"{prefix}{i:04d}", "pon_path": pon, "status": status, "rx_dbm": rx} for i in range(n)]

    olt_a = onus("DEMOA", 12, "online", "0/1/0", -21.5) + onus("DEMOB", 2, "offline", "0/1/0", None)
    olt_a += onus("DEMOC", 10, "los", "0/1/1", None)  # queda em massa na PON 0/1/1
    olt_a += [{"serial": "DEMODUP001", "pon_path": "0/1/0", "status": "online", "rx_dbm": -20.5}]  # mesmo serial em 2 OLTs (ambíguo)
    snaps = [
        ("OLT-DEMO-01", "huawei", "MA5800-X7", "R018", olt_a),
        ("OLT-DEMO-02", "zte", "C300", "V2.1.0P3", onus("DEMOD", 8, "online", "1/2/1", -19.25) + [{"serial": "DEMODUP001", "pon_path": "1/2/1", "status": "online", "rx_dbm": -20.0}]),
    ]
    for name, vendor, model, fw, items in snaps:
        pons = sorted({o["pon_path"] for o in items})
        r = c.post("/v1/edge/olt-snapshots", headers=h, json={
            "edge_id": edge, "observed_at": datetime.now(UTC).isoformat(), "name": name, "vendor": vendor, "model": model,
            "firmware": fw, "driver_level": "identified", "pons": [{"pon_path": p, "status": "up", "complete": True} for p in pons],
            "onus": items})
        assert r.status_code == 202, r.text
    r = c.post("/v1/edge/cpe-snapshots", headers=h, json={"edge_id": edge, "observed_at": datetime.now(UTC).isoformat(), "cpes": [
        {"canonical_serial": f"DEMOCPE{i:03d}", "vendor": "Huawei", "model": "HG8245H",
         "binding": {"protocol": "tr069", "external_id": f"DEMO-OUI-HG8245H-DEMOCPE{i:03d}", "connector_id": "genieacs-demo"}} for i in range(5)]})
    assert r.status_code == 202, r.text
    # --- como administrador do provedor: importa clientes fictícios e cria operações ---
    u = httpx.Client(base_url=API, timeout=15)
    ut = u.post("/v1/auth/token", json={"email": EMAIL, "password": PW}).json()["access_token"]
    uh = {"Authorization": f"Bearer {ut}"}
    csv_body = ("erp_customer_id,display_name,document,contract_status,onu_serial\n"
                "D001,Cliente Demo Um,,active,DEMOA0000\nD002,Cliente Demo Dois,,active,DEMOA0001\n"
                "D003,Cliente Demo Três,,suspended,DEMOD0000\nD004,Cliente Demo Ambíguo,,active,DEMODUP001\n")
    r = u.post("/v1/erp/import-csv?source=csv-demo", headers={**uh, "content-type": "text/csv"}, content=csv_body.encode())
    assert r.status_code == 200, r.text
    olt_id = next(o["id"] for o in u.get("/v1/olts", headers=uh).json() if o["name"] == "OLT-DEMO-01")
    cpe_id = u.get("/v1/cpes", headers=uh).json()[0]["id"]
    for i, (op, tgt) in enumerate([("collect", olt_id), ("reboot_cpe", cpe_id), ("set_wifi_ssid", cpe_id)]):
        j = u.post("/v1/jobs/preview", headers={**uh, "Idempotency-Key": f"demo-seed-job-{i:04d}"}, json={"operation": op, "target_id": tgt})
        assert j.status_code == 201, j.text
        if op == "collect":
            assert u.post(f"/v1/jobs/{j.json()['id']}/submit", headers=uh).status_code == 200
    print(f"tenant={tenant}\nemail={EMAIL}\npassword={PW}")


if __name__ == "__main__":
    sys.exit(main())
