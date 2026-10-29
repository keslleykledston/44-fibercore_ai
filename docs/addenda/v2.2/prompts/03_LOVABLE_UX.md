# Prompt Lovable — UX para roadmap v2.2 FiberCore

Faça protótipos e componentes React/TS exportáveis **para o FiberCore AI**. O domínio oficial será `https://fibercore.devops.k3gsolutions.com.br`; a rota de ajuda é `/ajuda`.

Identidade premium K3G, minimalista e futurista inspirada na clareza do iOS/macOS (não copiar interfaces, logos nem fontes proprietárias). Diretriz: **nada poluído**. Até 6 grupos de navegação, busca universal protagonista, 4 KPIs no máximo acima da dobra, 1 gráfico inicial, hierarquia discreta, conteúdo progressivo, ações contextuais, estados `loading/empty/error/stale/unknown/forbidden`, teclados e contraste WCAG 2.2 AA.

Prototipar em ordem: (1) Subscriber 360, (2) Guided Troubleshooting, (3) NOC Command Center, (4) Network Explorer, (5) Wi-Fi Experience, (6) Automation Studio; incluir Health/Update Center. Para cada uma: telas 1440x900 e 390x844, fluxos de 3 passos, componentes, tokens, descrição de states, `help_slug` e rota API correspondente. Não inventar dados ao vivo, nem criar back-end Lovable de produção.

Sinalizar `optical_health=insufficient_data` e `home_experience=insufficient_data` quando faltarem medições. No Subscriber 360, separar visualmente OLT/ONU, CPE (TR-069/USP), assinante/ERP e diagnóstico; credenciais nunca exibidas.

Entregar handoff compatível com Next.js/shadcn, com mock sintético, componentes reutilizáveis e definição de comportamento. O Claude Code integrará e capturará screenshots reais para a Central de Ajuda; imagens dos protótipos não substituem screenshots de aplicação funcionando.
