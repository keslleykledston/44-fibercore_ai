# Relatório de entrega — FiberCore AI (2026-10-28)

Estado: **LAB / pré-produção**. Nada publicado; nenhum equipamento real nem GenieACS real acessado; nenhuma escrita em rede. Repositório: github.com/keslleykledston/44-fibercore_ai (`main`). Todas as branches foram revisadas pelo Codex (adversarial-review) até `approve`; cada rodada com achados foi corrigida e testada (histórico em `docs/wiki/reviews/` e nos commits `fix(...)`).

## O que existe (com prova)
| Área | Entrega | Prova |
|---|---|---|
| Plataforma | FastAPI, PostgreSQL com RLS forçada e role sem BYPASSRLS, tenants/usuários/papéis/service accounts, audit append-only, lockout de login | pytest 114 |
| Eventos | Outbox transacional + JetStream, relay de menor privilégio, consumidor idempotente, replay, DLQ | testes de restart/duplicidade/mutação |
| Edge (Go) | Outbound-only, allowlist local anti-SSRF, NBI GET-only, fila SQLite com backpressure, drivers OLT Huawei/ZTE **read-only** (nível `identified`, fixtures SINTÉTICAS), SSH com host key pinada, jobs assinados Ed25519 | go test -race (9 pacotes) |
| Dados | Inventário com frescor (silêncio ≠ offline), ingestão idempotente/ordenada, ERP CSV (LGPD: documento só HMAC+last4), associação ONU↔cliente com revisão humana, incidentes por PON (dedupe/histerese) | pytest + golden Go→API |
| Operações | Job gate (preview→aprovação→despacho assinado→resultado verificado); **escrita bloqueada** (`HOMOLOGATED_WRITES` vazio; `ReadOnlyOps` compilado no Edge) | testes de bloqueio/2-pessoas/replay |
| Web | Next.js (BFF com cookie HttpOnly, tokens iOS-like claro/escuro), 7 telas, Central de Ajuda `/ajuda` com 7 How-to **publicados** e capturas reais (desktop/mobile) | `scripts/e2e.sh` 27+ (inclui axe WCAG 2.2 AA) |
| Infra | Compose (profiles), Caddy `/api/v1`→`/v1`, rotas internas 404, backup/restore verificado (cifra opcional), SBOM, pip-audit, trivy, gitleaks | `scripts/test-proxy.sh` 16/16 |

## O que NÃO existe / bloqueia produção
1. DNS/TLS/ACME e publicação em `fibercore.devops.k3gsolutions.com.br` — **não feitos** (dependem de infraestrutura e gate).
2. MFA, refresh de token, rate-limit completo na borda, CSP/HSTS, rotação de chave de job (kid), cofre de segredos.
3. Drivers de OLT **nunca testados em equipamento real**; promover a `observed` exige captura de laboratório sanitizada. GenieACS real não conectado.
4. USP/TR-369, Release Center, Copiloto (ADR-0015), K3s/HA, observabilidade (Prometheus/Grafana).
5. Workflows de GitHub Actions definidos mas **nunca executados** remotamente (sem `gh`).
6. Proposta Lovable recebida (docs/ux/lovable) mas não integrada ao código; revisão visual do Lovable pendente.

## Como reproduzir
`make venv && scripts/test-env.sh start && PYTHON=.venv/bin/python scripts/test-env.sh run` · `cd agents/edge && go test -race ./...` · `scripts/e2e.sh` · `scripts/test-proxy.sh` · `scripts/sbom.sh` · `scripts/secrets-scan.sh` · `scripts/backup.sh` + `scripts/restore-verify.sh`.

## Próximos passos recomendados (ordem)
1. Campo: capturas reais de OLT (firmware exato) + NBI GenieACS de laboratório → promover drivers com evidência.
2. W9: MFA, refresh, CSP/HSTS, rate-limit na borda, DNS/TLS reais, rodar CI no GitHub.
3. Observabilidade + ensaio de falha/restore; só então piloto interno supervisionado (`INTERNAL_PILOT`).
4. USP (controlador de lab), Release Center, Copiloto — cada um com ADR e gate.
