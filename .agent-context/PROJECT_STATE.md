# Project State — FiberCore AI

- As of 2026-10-28: Sprint 0 completa, Sprint 1 completa, Sprint 2 (backend) completa, Sprint 3 parcial (job gate). Adendo v2.1 aplicado na base (docs/config/proxy); **frontend ainda não existe**.
- Repo remoto: github.com/keslleykledston/44-fibercore_ai (push autorizado; via SSH 443, chave id_ed25519_github; `core.sshCommand` local). main = último PR aprovado pelo Codex.
- Pronto e testado: API (auth/RLS/tenants), outbox+JetStream, Edge Go (allowlist, NBI GET-only, fila SQLite, drivers OLT Huawei/ZTE `identified` com fixtures SINTÉTICAS, jobs assinados), ERP CSV/associações, incidentes NOC, job gate (escrita bloqueada), supply chain, backup/restore verificado, proxy Caddy (profile public).
- NÃO feito: UI (W1–W9), USP adapter, release center, copiloto, DNS/TLS real, MFA/refresh/rate-limit, hardware/GenieACS reais.
- Regras: sem escrita em rede; Codex adversarial-review obrigatório por branch (`node .../codex-companion.mjs adversarial-review --wait --base main --scope branch`); ff-merge em main + push após approve.
- Testes: `scripts/test-env.sh start && PYTHON=<venv>/bin/python scripts/test-env.sh run`; `cd agents/edge && go test -race ./...`; `scripts/test-proxy.sh`.
