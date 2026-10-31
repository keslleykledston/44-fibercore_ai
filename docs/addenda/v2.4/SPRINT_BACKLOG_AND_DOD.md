# Backlog executável para incluir após a sprint atual (sem reiniciar projeto)

## FC24-00 — GAP e ADR (primeiro PR)
- Inventariar repositório, comparar PRD/API/Cap Registry/Subscriber 360/Jobs/Edge/Help com esta especificação.
- Mapear quais entidades, routes, tests e interfaces já existem; documentar incompatibilidades em `docs/wiki/adr` e manter histórico.
- Aprovar schema aditivo, sem duplicação de RBAC, filas ou widgets; relatório de impacto e DoD.

## FC24-01 — Capabilities e formulários read-only
- Enumerar Wi-Fi radios, SSIDs, APs, LAN, WAN de fixtures sintéticas TR-098/181/USP.
- Resolver instâncias reais, grupos e grau de certificação. Tipar schema de formulário.
- `GET /.../capabilities`, `/configuration`, `/form-schema`, com fresh/source e sem secrets.
- Testar sem capacidades/sem radio/Wi-Fi inativo/ACS unavailable/multiSSID/dual stack.

## FC24-02 — UI Sidebar + help
- Criar UI drawer recolhível com miniatura, status, timestamps, abas, forms dinâmicos, sem write real.
- Implementar default read-only; UX Lovable handoff e testes de usabilidade N1/N2.
- Gerar screenshots reais e How-to `/ajuda/ont/...` conforme pipeline v2.1.

## FC24-03 — Preview e policy + jobs
- Criar change-set intent, otimista `If-Match`/snapshot revision, diff redigido, risk e approvals.
- Reutilizar automation-jobs/outbox, lock por physical device/capability, nonce+TTL, fail closed e flags.
- Backend nunca aceita caminho CWMP/USP arbitrário da UI; only capability id com mapping certificado.

## FC24-04 — GenieACS safe adapter
- Implementar NBI read/write limitado e devidamente tipado **dentro do Edge**, com lab/test doubles.
- Validar resposta HTTP 200/202 e ciclo session → pós-check. Não tocar presets do GenieACS real sem autorização.
- Fazer homologação inicial de SSID ou habilitar rádio por uma combinação ONT/model/firmware; teste laboratório autorizado.

## FC24-05 — Wi-Fi abrangente P1
- Senha write-only, canal auto/manual, largura, potência Wi-Fi apenas com constraints certificadas.
- Testar desconexão do cliente, conflito dual-stack, reauth e falhas de sessão, sem retries perigosos.

## FC24-06 — LAN e WAN de alto risco
- Exigir OOB recovery, revisão de conectividade, janelas, dupla aprovação, simulador de falha e plano de rollback específico.
- Habilitar leitura antes de alterações; homologação escrita separada por modelo/firmware.

## FC24-07 — USP adapter (quando Controller real estiver homologado)
- Reutilizar USP Controller independente, consumir `GetSupportedDM`, `Get`/`Set`/`Operate`, com lock comum TR-069/369.
- Sem controller real, teste via mock, feature off, UI mostra indisponibilidade.

## FC24-08 — Finalização e métricas
- Dashboard de operações, logs redigidos, rollback/reconciliation, wiki + changelog; P95 e taxas medidas.
- Codex review, Lovable UX, smoke E2E + failure injection; publicar somente após gate humano.

## Definition of Done por story
Contrato API versionado+schema validado, migration aditiva, security tests multi-tenant, mocks e fixture, async job state, métricas, logs redigidos, UI states (empty/stale/403/unknown/error), capturas Playwright reais, How-to, memória local, ADR, testes reais+evidências, Codex PASS ou bloqueio explícito; nenhuma execução em produção na mesma PR de laboratório.
