# Central de Ajuda e documentação em cada PR visual

1. Criar `help_slug` estável, por exemplo `/ajuda/assinantes/visao-360`.
2. Construir componente UI funcional com usuário de teste e fixtures sintéticas, integração API real ou mock de teste claramente rotulado.
3. Rodar Playwright com cenário estável, browser/viewport 1440×900 e 390×844, aguardar estado pronto; coletar screenshots **reais** no app sob `docs/help/assets/<slug>/desktop.png`, `mobile.png`.
4. Escrever How-to em PT-BR: objetivo, permissões, passos, imagens/alt, resultado esperado, problemas frequentes, status e versão/commit, data de última verificação.
5. Ligar HelpContextLink ao artigo e adicionar manifesto de imagens (status `draft` até verificar). Com teste E2E e captura real, `published` com autorização.
6. Mudou layout, texto de botão ou fluxo? Regenerar captura, revisar manual no **mesmo PR**. Screenshot de Lovable é design, não evidência operacional.
7. Codex bloqueia screenshot falso, imagens com dados sensíveis, caminho quebrado ou manual desatualizado. Wiki de engenharia permanece interna e isolada da Central de Ajuda de usuários.

## Template
```markdown
---
title: Consultar Assinante 360
slug: assinantes/visao-360
status: draft
role: [noc_n1, noc_n2, support]
product_version: pending
last_verified: pending
---
# Consultar Assinante 360
**Objetivo:** ...
**Antes de começar:** ...
1. Pesquise ...
2. Abra ...
3. Confira origem e data da coleta ...
![Visão geral real da aplicação](../assets/assinantes/visao-360/desktop.png)
**Resultado esperado:** ...
**Se não funcionar:** ...
```
A imagem acima é **modelo de link**, não indica arquivo gerado neste pacote.
