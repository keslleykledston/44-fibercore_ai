# Central de Ajuda do FiberCore AI — fonte de conteúdo de usuário

A Central de Ajuda será acessível dentro da plataforma em **`https://fibercore.devops.k3gsolutions.com.br/ajuda`**. Publicação dependente de autenticação implementada; neste pacote há apenas especificação e exemplos **ainda não publicados**.

- Cada tela/fluxo tem `help_slug` e link contextual `Ajuda`.
- Artigos em PT-BR organizados por tarefa, papéis NOC/Engenharia/Atendimento/Admin, busca e índice.
- Cada manual publicado deve ter objetivo, pré-requisitos/permissões, passos curtos, **capturas reais do frontend integrado**, resultado esperado, falhas comuns, data/versão e links relacionados.
- Os manuais não incluem credenciais, IP de clientes, documentos pessoais ou dados de produção. Capturas com fixtures sintéticas estáveis; anonimização adicional quando necessário.
- O design da Central segue `docs/ux/DESIGN_SYSTEM_IOS_LIKE.md`.

## Como uma tela vira documentação

1. Lovable entrega protótipo, estados, fluxo e `help_slug` no handoff.
2. Claude implementa tela ligada à API (ou estado mock **explicitamente isolado**, não em produção).
3. Criar E2E Playwright com dados de teste estáveis e screenshot desktop/mobile e estados relevantes.
4. Armazenar imagens em `docs/help/assets/<slug>/desktop.png`, `mobile.png`, etc.
5. Escrever artigo a partir de `docs/help/HOWTO_TEMPLATE.md`, referenciando screenshots reais com alt e legendas; **captura gerada antes do texto que a descreve**.
6. Atualizar `docs/help/screenshot-manifest.yaml`: status `published` apenas quando a captura e a revisão humana estiverem completas.
7. Codex verifica coerência tela/captura/instruções e nenhuma exposição de segredos; registrar evidência do commit.
8. Atualizar screenshot e artigo no **mesmo PR** sempre que layout/fluxo mudar. Capturas obsoletas BLOQUEIAM merge da tela.

## Publicação

Implementar rota protegida Next.js `/ajuda` e `/ajuda/[slug]` com Markdown sanitizado e metadados. Não servir `docs/engineering`, ADRs, prompts internos ou wiki operacional para usuários do SaaS. O MkDocs é wiki técnica interna/local; a ajuda pública é uma coleção filtrada. Busca de artigos deve respeitar idioma, role, versão e visibilidade do tenant.
