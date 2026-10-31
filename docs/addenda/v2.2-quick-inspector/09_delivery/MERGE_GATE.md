# Critérios de merge Codex / release

[ ] Código ativo inspecionado, git status e divergências documentadas  
[ ] Não alterou contratos/ADRs vigentes sem aprovação  
[ ] Reutiliza o shell, drawer, components e tokens existentes  
[ ] Inventário, PON tree, 360° e navegação preservados  
[ ] Não cria dependência obrigatória de ACS/ERP/USP  
[ ] Não inventa estados, cliente, potência, freshness, LEDs, capabilities  
[ ] Distinção explícita OLT vs ACS vs ERP e `unknown/stale`  
[ ] Dados por tenant/RLS + RBAC/PII, testes de tenant cruzado  
[ ] Nenhum write, action remota/execução de LLM criada no adendo  
[ ] UI 1440x900, 390x844, zoom 200%, light/dark, keyboard/ESC/foco  
[ ] `prefers-reduced-motion`, WCAG 2.2 AA, mensagens em pt-BR  
[ ] Race de seleção A/B/C, cache tenant-aware, abort/cancel, estados parciais  
[ ] Feature flag OFF funciona como rollback  
[ ] TSC, lint, unit, integration, E2E, acessibilidade, build, screenshots reais  
[ ] Help by construction: screenshots em docs/help/assets, how-to, manifest, validate_help.py  
[ ] Changelog, docs/wiki/IMPLEMENTATION_STATUS.md, .agent-context atualizado  
[ ] Lovable: hierarquia/densidade/mobile aprovados; Codex: PASS sem BLOCK  
[ ] Evidências de teste anexadas ao PR, sem afirmar feature em produção antes da verificação

## Critérios de aceite do usuário
- Uma ONU selecionada expõe um painel lateral claro e recolhível.
- É possível trocar a seleção sem sair da lista.
- Resumo exibe dados confiáveis, miniatura genérica se necessário e abre Visão 360°.
- O operador distingue falha ACS de falha PON.
- Nada quebra na versão 2.2 e nenhuma função de manobra foi introduzida.
