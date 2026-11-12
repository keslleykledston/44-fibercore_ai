# CSP com nonce: o que o dono do host precisa mudar no nginx

Escopo: nginx do HOST (`/etc/nginx/...`, exige root; NÃO é alterado pelo repositório). Decisão e política: `docs/wiki/adr/ADR-0042-csp-com-nonce-por-requisicao-no-web.md`.

## Estado de partida (hoje)
- `infra/deploy/nginx/fibercore.devops.k3gsolutions.com.br.conf` impõe `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; …` (sem nonce, sem `strict-dynamic`).
- `infra/deploy/nginx/fibercore_proxy.inc` tem `proxy_hide_header Content-Security-Policy;`: o CSP vindo do web (Next) é descartado.
- Efeito: mesmo com `FIBERCORE_CSP_MODE=enforce` no app, o navegador só vê o CSP do host. A defesa contra XSS continua inexistente até o item 1 abaixo.

## Fase 1: observar (NENHUMA mudança no host)
O app sobe em `report-only` (padrão) e emite `Content-Security-Policy-Report-Only`. O `proxy_hide_header` atual só esconde o nome `Content-Security-Policy`; o `-Report-Only` atravessa o nginx. Abra a LAB com o console do navegador aberto, navegue as telas e confirme zero linhas `[Report Only] Refused to …`. Conferir o cabeçalho:

```
curl -sI https://fibercore.devops.k3gsolutions.com.br/login | grep -i '^content-security-policy'
```
Esperado: o do host (enforce, com `unsafe-inline`) E um `content-security-policy-report-only` com `'nonce-…' 'strict-dynamic'` (nonce diferente a cada chamada).

## Fase 2: o dono do host muda o nginx (root)
Só depois de a Fase 1 mostrar zero violações.

1. `fibercore_proxy.inc`: REMOVER a linha `proxy_hide_header Content-Security-Policy;`. (Não esconder `Content-Security-Policy-Report-Only`.)
2. `fibercore.devops.k3gsolutions.com.br.conf`: REMOVER a linha `add_header Content-Security-Policy "…" always;`. O nginx não consegue produzir nonce por requisição; manter a política dele só seria redundante (dois CSPs = o navegador aplica a interseção; o do host, mais frouxo, não enfraquece o do app, mas o app deve ser a fonte única).
3. `sudo nginx -t && sudo systemctl reload nginx`.
4. No `.env.prod` da LAB: `FIBERCORE_CSP_MODE=enforce`; recriar só o contêiner `web` (`docker compose -p fibercore-prod --env-file .env.prod -f infra/compose/compose.yaml --profile public up -d web`). A variável é lida em tempo de execução: sem rebuild.
5. Conferir:
```
curl -sI https://fibercore.devops.k3gsolutions.com.br/login | grep -i '^content-security-policy'
```
Esperado: UM `content-security-policy` com `script-src 'self' 'nonce-…' 'strict-dynamic'`, `style-src 'self' 'nonce-…'`, `object-src 'none'`, `frame-ancestors 'none'`; sem `unsafe-inline` em `script-src`/`style-src`; nenhum `-report-only`. Repetir a chamada: o nonce muda. Logar e navegar com o console aberto: zero `Refused to …`.

Rollback imediato (sem root): `FIBERCORE_CSP_MODE=report-only` (ou `off`) e recriar o `web`. Se o host já não esconde o CSP do upstream, em `off` o navegador fica SEM CSP (o do host foi removido no item 2): restaure o `add_header` antigo do template do repositório se precisar voltar ao estado anterior.

## HSTS sem includeSubDomains
Hoje: `add_header Strict-Transport-Security "max-age=31536000" always;` (só o host exato). Para cobrir subdomínios:
```
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```
Antes de aplicar, decisão do dono: o DNS é wildcard `*.devops.k3gsolutions.com.br` e o nginx é compartilhado por vários projetos. `includeSubDomains` faz o navegador exigir HTTPS em TODOS os subdomínios por 1 ano (qualquer vhost só HTTP, ou certificado vencido, passa a ficar inacessível para quem já visitou o FiberCore). Confirme que todos os vhosts de `*.devops.k3gsolutions.com.br` têm TLS válido e renovação ativa. NÃO usar `preload` sem decisão formal (irreversível na prática). Este é o único item de HSTS: o app web não emite HSTS (o nginx é a única fonte; `proxy_hide_header Strict-Transport-Security` permanece).

## Lembretes
- Nenhum CDN/cache de HTML na frente do app: o HTML é por requisição e traz o nonce; HTML cacheado reaproveitaria nonce e quebraria os scripts. `/_next/static/*` pode ser cacheado.
- O repositório só guarda o template em `infra/deploy/nginx/`; o arquivo vivo do host é do dono do host.
