# ADR-0013: Design system iOS-like e ajuda por construção (screenshots + How-to)

Status: Proposed | Data: 2026-10-28 | Owner: Claude Code (implementação), Lovable (proposta UX), Codex (revisão)

## Decisão
- Adotar `docs/ux/DESIGN_SYSTEM_IOS_LIKE.md` e `configs/ui/design-tokens.json` (CSS variables/Tailwind theme, tema claro/escuro, ≤4 KPIs, ≤6 áreas de navegação, progressive disclosure, estados explícitos: stale ≠ offline).
- Frontend `apps/web` (Next.js + TypeScript + Tailwind/shadcn). Lovable propõe a UX; Claude integra componentes aprovados; screenshots finais vêm **da aplicação integrada**, nunca do mock Lovable.
- Cada tela concluída gera, no MESMO PR: screenshots Playwright reais (1440×900 e 390×844, + estados), How-to em `docs/help/how-to/<slug>.md`, entrada em `docs/help/screenshot-manifest.yaml`, `HelpContextLink` → `/ajuda/<slug>`, e `python tests/validate_help.py` verde. Sem screenshot real, o artigo fica `draft` (nunca se alega captura).
- Dados das capturas: fixtures sintéticas, locale pt-BR, TZ America/Manaus, relógio fixo; sem PII/credenciais.
- Central de Ajuda `/ajuda` autenticada e pesquisável; serve apenas `docs/help/` (nunca `docs/architecture`, agentes, prompts).
- CI adiciona `validate_help.py`; Codex BLOQUEIA UI sem screenshot+How-to+a11y+E2E.

## Consequências
Telas já implementadas: **nenhuma** (só API/Edge/CLI) — as "tarefas de adequação" viram o backlog W1–W9 em `docs/product/ROADMAP_BACKLOG.md`. Custo: pipeline Playwright (download de Chromium) e disciplina de docs por PR.
