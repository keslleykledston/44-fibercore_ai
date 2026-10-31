# Plano incremental — entregas pequenas, sem atropelar FiberCore 2.2

## Pré-flight obrigatório
- `git status`, branch atual, matriz de versões e `docs/wiki/IMPLEMENTATION_STATUS.md`.
- Descobrir UI: AppShell, drawer, design tokens, hooks de inventário/ONU360, router, contracts, RBAC, tests.
- Descobrir origem real do código; o repositório público de referência constou vazio na consulta de 2026-10-30. Não inicializar monorepo novo sem confirmação do principal.
- Registrar divergências entre kit, docs e repositório. Não implementar arquitetura alternativa.

## PR 1 — UI shell/seleção, SEM rede
Arquivos esperados (adaptar ao projeto): `components/onu/OnuQuickInspector.tsx`, UI shared drawer quando necessário, selectors e story/fixture.  
- Abrir/fechar/trocar seleção no inventário e na árvore PON; estados loading/empty/error.
- Responsivo, foco, ESC, política de um único painel contextual, `help_slug`.
- Reutilizar tokens/StatusPill/DataFreshness, dark/light.
**Gate:** teste componente + story + screenshots com fixtures sintéticas claramente marcadas.

## PR 2 — View model e dados reais READ-ONLY
- Adaptar hooks/clientes existentes à view model, sem inventar endpoint.
- Exibir PON, ACS e optical separados, timestamps/estados; cliente apenas associação e RBAC.
- Testar race A/B/C, erros isolados OLT/ACS/ERP, stale, null, modelo desconhecido.
- Se contrato novo necessário, propor revisão específica e aguardar aceite antes de criar API/migrações.
**Gate:** testes multi-tenant, payloads/erros, logs sem PII, nenhum write.

## PR 3 — Miniatura, navegação, docs
- SVG genérico + capability opt-in para modelo homologado, `prefers-reduced-motion`.
- Link real 360°, preservar contexto. CTA Investigar condicional (somente se fluxo existente).
- Ajuda contextual e capturas reais via Playwright, acessibilidade, changelog.
**Gate:** E2E com navegação desktop/mobile, Codex PASS, handoff visual Lovable aprovado.

## Rollout
- Feature flag desativada por padrão, staging com dados sintéticos, QA e integração autorizada.
- Habilitar piloto por tenant/perfil conforme governança existente; rollback OFF preserva lista/360°. Não declarar feature ativa sem deploy.
- Monitorar performance da consulta e regressões do inventário/árvore.

## Não adicionar
Microserviço, tabela, Kafka/NATS novo, novo backend de IA, novo ACS, WebSocket se o app não usa, biblioteca 3D, writes, telas extras de ONU.
