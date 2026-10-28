# Project State — FiberCore AI

- As of 2026-10-27: Sprint 0 PR 1 pronto para review (branch `sprint0/01-foundation`, local; sem remote, sem push).
- Feito e testado: API (livez/readyz/version/modules com probes reais), auth JWT+Argon2id, tenants/users/roles/service accounts, RLS forçada com role sem BYPASSRLS, audit append-only, Compose (postgres+nats+migrate+api) saudável, 18 testes PASS.
- Não feito: outbox relay/consumer, mock Edge/NBI, SBOM/scan/backup, Codex gate, domínio de rede (OLT/ONU/CPE).
- Stack: FastAPI+PostgreSQL+NATS+Go Edge+Next.js. GenieACS só via NBI/Edge privado. Hardware não validado; nada de escrita em rede.
- Porta dev da API: 18420 (8000/8001/8002/18000 ocupadas por outros projetos). Venv de trabalho fora do repo: /data/cafegpt/tmp/fc-venv (ou `make venv` → .venv).
- Status detalhado: `docs/wiki/IMPLEMENTATION_STATUS.md`; evidências: `docs/wiki/TEST_EVIDENCE.md`.
