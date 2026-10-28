# ADR-0012: Domínio público, proxy reverso e prefixo `/api/v1`

Status: Proposed (aguarda Codex gate) | Data: 2026-10-28 | Owner: Claude Code

## Contexto
Adendo v2.1: frontend em `https://fibercore.devops.k3gsolutions.com.br`, API em `/api/v1`, Central de Ajuda em `/ajuda`, HTTPS obrigatório e configurável por variáveis. A API implementada expõe rotas `/v1/*` (e `/livez`, `/readyz`, `/version` na raiz).

## Decisão
- Contrato OpenAPI: `servers: [{url: /api/v1}]` (0.7.0-draft). **O código da API não muda**: o proxy remove somente o prefixo `/api` (`/api/v1/x` → `api-core:8000/v1/x`).
- Proxy = Caddy, serviço `proxy` no Compose sob **profile `public`** (não sobe por padrão; aditivo, não altera serviços existentes). Dev: `infra/deploy/Caddyfile.dev` (HTTP em loopback). Produção: `Caddyfile.example` com host/ACME por variável (`FIBERCORE_PUBLIC_HOST`, `ACME_EMAIL`).
- Somente o proxy é publicável. `/livez`, `/readyz`, `/metrics`, `/internal`, `/docs`, `/openapi.json` retornam 404 no proxy. Postgres/NATS/Mongo/NBI nunca publicados.
- Nada é publicado agora: `configs/deployment/public-domain.yaml` é intenção; DNS/TLS/deploy dependem de infraestrutura real e do gate (auth+RLS+testes+TLS+Codex).

## Consequências
`scripts/test-proxy.sh` prova o mapeamento e o bloqueio de rotas internas (10 checks PASS) e que nenhuma porta fica em 0.0.0.0. Pendências: CSP/HSTS (só após TLS real), rate limit, DNS-01 se necessário, cookies Secure/HttpOnly/SameSite (ADR-0014).
