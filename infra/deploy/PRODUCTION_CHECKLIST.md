# Publicação do frontend — checklist de aceite

**Hostname único:** `fibercore.devops.k3gsolutions.com.br`. **Status:** publicado em `LAB` com TLS em 2026-10-28 atrás do nginx do host (ADR-0016). Itens abaixo ainda abertos bloqueiam `INTERNAL_PILOT`.

- [ ] Infra definida e DNS confirmado em A/AAAA; nenhum IP inventado.
- [ ] Next.js real pronto com `/`, `/ajuda` e fluxo de autenticação funcionando.
- [ ] Core API de produção, no prefixo `/v1`, com middleware de autenticação/autorização/RLS.
- [ ] Caddy/Ingress: `/api/v1` -> `/v1` interno; `/ajuda` -> Next.js; TLS/redirect funcionam.
- [ ] Segredos externos, `DEMO_MODE=false`, sem Swagger/debug/API de métricas públicos.
- [ ] Somente 443 (e 80, se aplicável) aberto ao público; NBI/Mongo/Postgres/NATS restritos.
- [ ] Logs sem credenciais/PII, monitoramento de TLS/latência/5xx, backup e recuperação.
- [ ] Testes E2E Chrome/Firefox/mobile: login, troca tenant, busca, ações negadas, ajuda.
- [ ] A11y WCAG 2.2 AA, performance e revisão de telas Lovable/Codex.
- [ ] Screenshots **reais** em desktop/mobile e how-to de cada fluxo publicado.
- [ ] Plano de canary/rollback testado, e registro de versão, data, SHA e aprovador.

- [ ] `web` com uma única réplica (renovação de sessão coalescida em memória, ADR-0017); escalar só depois de coordenação compartilhada do refresh.
