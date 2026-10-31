# Acessibilidade e responsividade

- `aside` não-modal em desktop largo; `dialog` ou Drawer modal em mobile com `aria-modal=true`, foco preso, `inert`/scroll bloqueado no fundo.
- Foco inicial em título ou fechar, ESC fecha em modo modal (pode também fechar no desktop), retorna foco ao gatilho original.
- Se lista virtualizada remove gatilho da DOM, fallback de foco para lista/título principal.
- `aria-labelledby`, rótulos em todos os controles, estados com texto + cor + ícone; nunca só LED ou hover.
- `prefers-reduced-motion: reduce`: desativar pulse/shimmer, mantendo status. Para animação normal: máximo 120–220ms transição e microefeito raro.
- Contraste WCAG 2.2 AA; inputs e botões ~44px em touch; teclado de ponta a ponta.
- Campo de status atualizado não deve disparar `aria-live` a cada polling; anunciar somente troca relevante de ONU/erro de carregamento.
- 1440x900 e 390x844 como snapshots obrigatórios, também testar 1024px e zoom 200%.
- Rolagem somente no corpo interno, header/CTA alcançáveis; sem scroll horizontal.
- Consistência visual com design system: contorno mínimo, sem densidade excessiva, dark/light, Português Brasil.
