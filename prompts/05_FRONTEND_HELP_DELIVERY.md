# PROMPT OPERACIONAL — Claude Code + Lovable + Codex (tela -> ajuda)

Você está implementando uma tela do FiberCore AI, publicado futuramente no domínio **`https://fibercore.devops.k3gsolutions.com.br`**. Execute **um fluxo vertical por PR**; não entregue apenas mock nem declare URL em produção antes do deploy.

1. Leia `docs/ux/UX_SPEC.md`, `docs/ux/DESIGN_SYSTEM_IOS_LIKE.md`, `configs/ui/design-tokens.json`, `docs/engineering/SCREENSHOT_AND_HOWTO_PIPELINE.md` e contratos OpenAPI.
2. Solicite/consuma a proposta Lovable para este fluxo: navegação simples, busca e ação principal evidentes, pouco ruído visual, estados loading/empty/error/stale/403, iOS-like original K3G, dark/light, responsivo.
3. Integre o frontend Next.js com API real ou fixtures sintéticas devidamente isoladas de produção; crie `help_slug` e link contextual para `/ajuda/<slug>`.
4. Escreva/execute E2E Playwright com fixtures estáveis e autenticação de teste. Capture screenshots REAIS após estado pronto: 1440x900 e 390x844, se possível também estados críticos. Não confunda mock Lovable com UI funcionando.
5. Atualize o manual em `docs/help/how-to/...` com título, objetivo, permissões, passos curtos, imagens reais, legendas, resultado esperado, problemas comuns, SHA, versão, última validação.
6. Atualize `docs/help/screenshot-manifest.yaml` e rode `python tests/validate_help.py`, lint/typecheck/E2E/acessibilidade. Capturas vencidas ou falta de docs == falha de entrega.
7. Abra PR pequeno com print de antes/depois, screenshot, How-to, testes, risco, rollback e evidência. Encaminhe Codex para veredito PASS/WARN/BLOCK. Corrija BLOQUEIOS; não aprove seu próprio PR.

**Bloqueios:** URL interna sem auth, dados fictícios não identificados em produção, segredos em screenshot/manual, screenshot inventado/arte Lovable usada como evidência real, navegação poluída ou botão de escrita sem capability/aprovação.
