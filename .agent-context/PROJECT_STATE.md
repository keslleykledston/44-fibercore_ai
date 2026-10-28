# Project State — FiberCore AI

- As of 2026-10-28: entrega LAB concluída até onde é possível sem campo (ver `docs/wiki/FINAL_REPORT.md`). main = tudo aprovado pelo Codex e enviado a github.com/keslleykledston/44-fibercore_ai (SSH 443, chave id_ed25519_github, `core.sshCommand` local).
- Pronto: API/RLS/auth+lockout, outbox+JetStream, Edge Go (+drivers `identified`, jobs assinados), inventário, ERP CSV/associações, incidentes, job gate (escrita BLOQUEADA), web Next.js + Central de Ajuda (7 How-to com capturas reais), proxy Caddy, supply chain, backup/restore.
- Pendente: DNS/TLS/publicação; MFA/refresh/CSP/HSTS; hardware/GenieACS reais; USP/Release Center/Copiloto (ADR-0015); CI remoto nunca rodado; revisão visual Lovable.
- Regras: sem escrita em rede; Codex adversarial-review por branch; ff-merge + push só depois de approve; nunca ler/ecoar `.env`.
- Testes: `scripts/test-env.sh`, `go test -race`, `scripts/e2e.sh`, `scripts/test-proxy.sh`. Portas dev: API 18420, proxy 18480, web (E2E) 18490 (8000/8001/8002/13000/18000 ocupadas por outros projetos).
