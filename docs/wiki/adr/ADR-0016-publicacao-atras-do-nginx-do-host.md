# ADR-0016 — Publicação atrás do nginx do host

Status: aceito (2026-10-28). Complementa ADR-0012 (proxy) e ADR-0014 (BFF).

## Contexto
O host já roda um nginx compartilhado em 80/443 com um vhost por projeto e certificados Let's Encrypt via certbot. DNS `*.devops.k3gsolutions.com.br` já resolve para o host (wildcard), então `fibercore.devops.k3gsolutions.com.br` não exigiu registro novo. A instrução do responsável foi usar o nginx existente.

## Decisão
- nginx do host termina TLS (certbot webroot, renovação pelo `certbot.timer`) e faz rate limit de login (10 req/min/IP) e de API; define os cabeçalhos de segurança (HSTS, CSP, Permissions-Policy, X-Frame-Options) e esconde os do upstream para não duplicar.
- Upstream único: Caddy do compose (profile `public`) em `127.0.0.1:18480`, com `Caddyfile.upstream` (`trusted_proxies private_ranges`). Mapeia `/api/v1` → `/v1`, bloqueia `/internal`, `/metrics`, `/docs`, `/openapi.json`, `/livez`, `/readyz`.
- `X-Forwarded-For` é sobrescrito no nginx (`$remote_addr`), nunca anexado.
- Stack de produção isolada do dev: `docker compose -p fibercore-prod --env-file .env.prod` (`make up-prod`). Segredos aleatórios em `.env.prod` (0600, ignorado pelo git). `FIBERCORE_JOB_SIGNING_KEY` vazio: despacho de jobs desligado (fail closed). Escritas em rede continuam bloqueadas.
- Sem dados de demonstração. Um tenant e um admin criados por CLI; credenciais em arquivo 0600 fora do repositório.

## Consequências
- Estado: `LAB` publicado com TLS. Não é `PRODUCTION_READY`.
- Pendências antes de `INTERNAL_PILOT` com dados reais: MFA, refresh token, rotação de chave (kid), cofre de segredos, monitoramento de TLS/5xx, ensaio de restore, CSP sem `unsafe-inline` (nonce).
- O vhost antigo `olt.devops...` (kit anterior, outro skeleton) não foi alterado.
