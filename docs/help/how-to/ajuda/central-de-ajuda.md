---
title: "Como usar a Central de Ajuda"
slug: "ajuda/central-de-ajuda"
role: [isp_admin, engineer, noc_n2, noc_n1, support]
status: published
product_version: "0.1.0"
last_verified: "2026-10-28"
help_owner: "Plataforma FiberCore"
ui_route: "/ajuda"
---

# Como usar a Central de Ajuda

**Objetivo:** encontrar o passo a passo de cada tela.

**Antes de começar:** Autenticação necessária. A ajuda só exibe manuais do produto.

## Passo a passo

1. Acesse **Ajuda** na barra superior ou clique em **Ajuda desta tela** em qualquer tela.
2. Use **Buscar na ajuda** para filtrar por palavra.
3. Abra o artigo; o rodapé mostra a versão do produto e a data da última validação.

![Tela em desktop 1440×900 — Como usar a Central de Ajuda](../../assets/ajuda/central-de-ajuda/desktop.png)

![Tela em mobile 390×844 — Como usar a Central de Ajuda](../../assets/ajuda/central-de-ajuda/mobile.png)

## Resultado esperado

A lista mostra os artigos; artigos ainda sem capturas validadas aparecem como **em elaboração**.

## Permissões necessárias

Qualquer papel autenticado.

## Se algo não funcionar

- **Artigo não encontrado:** o link pode ter mudado; volte à lista e busque pelo título.

## Evidências de documentação

- Build/commit: 1d9fb94 (árvore de trabalho do PR)
- Browser/viewport: Chromium; desktop 1440×900 e mobile 390×844
- Caso de teste E2E: help-screenshots.spec.ts › ajuda/central-de-ajuda
- Dados: fictícios (seed `scripts/seed_demo.py`); sem informações reais de clientes
