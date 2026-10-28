# FiberCore UI — design system premium, minimalista e iOS-like

**Direção:** inspirado em princípios de clareza, profundidade sutil e fluidez de interfaces iOS/macOS; **não copiar** telas, ícones proprietários, logotipos nem distribuir fontes Apple. Produto próprio K3G, desktop-first para operadores NOC, mobile acessível.

## 1. Regras de experiência (obrigatórias)

- Decisão primeiro: na tela inicial, **busca global + incidentes prioritários + até quatro KPIs**; no máximo um gráfico visível inicialmente. O resto por expandir/aba.
- Navegação principal com **no máximo 6 grupos**. Breadcrumb simples para `Rede > OLT > PON > ONU`. Evitar menus aninhados em excesso.
- Progressive disclosure: resumo limpo; detalhes ópticos/tabelas/comandos apenas por seleção. Preferir uma ação primária por contexto, secundárias em menu contextual.
- Não mostrar informações redundantes, bordas em todo elemento, sombras exageradas, cards gigantes, gradient neon, glassmorphism opaco sobre tabelas, bolhas e badges coloridos decorativos.
- Estado de dados explícito e discreto: `Atualizado há X`, `Sem coleta`, `Dados defasados`, `Conector indisponível`, `Tarefa pendente`. NUNCA confundir falha Edge/ACS/USP com ONU offline.
- Confirmações para write com resumo de alterações, impacto, permissão, aprovação e resultado; não representar `queued` como `success`.
- Acessibilidade: contraste WCAG 2.2 AA, foco visível, teclado completo, rótulos, suporte `prefers-reduced-motion`, tooltips não exclusivos para informação crítica.

## 2. Tokens de interface

Consolidar tokens em `configs/ui/design-tokens.json`; implementar como CSS variables/Tailwind theme e componentes shadcn. Fonte: system UI (`-apple-system`, BlinkMacSystemFont, `Inter`, `Segoe UI`, sans-serif), sem empacotar SF Pro. Grade 8pt (ajustes 4px), radius de 10–16px conforme densidade, animações 120–220 ms, painel com borda 1px e sombra mínima. Sidebar com seleção precisa, topbar com busca universal (atalho `Cmd/Ctrl+K`).

- Fundos neutros/claros (e dark mode), azul K3G como acento funcional e cor reservada para severidade real.
- Espaçamento generoso sem sacrificar densidade de tabela. Default página operacional max-width 1440px com tabela em área fluida.
- Rótulos claros, conteúdo em Português (Brasil), unidades consistentes (dBm, ms, Mbps, %) e horários locais com timezone indicado.
- Alvos interativos confortáveis (~44px quando touch); teclas e leitores de tela testados.
- Estados padronizados: skeleton, empty com CTA, stale, offline, forbidden, loading, erro recuperável, aprovação pendente.

## 3. Componentes reutilizáveis

`AppShell`, `CompactSidebar`, `GlobalSearch`, `PageHeader`, `KpiStrip`, `DataFreshness`, `StatusPill`, `VirtualizedGrid`, `FilterBar`, `EntityDetailDrawer`, `ConfirmOperationSheet`, `ApprovalTimeline`, `ModuleHealthTable`, `HelpContextLink`, `EmptyState`, `ErrorState`, `IncidentQueue`, `PonTree`, `DeviceSummary`.

`HelpContextLink` abre o manual correspondente em `/ajuda/<slug>`; toda tela deve ter `help_slug` estável. Não usar ícones sem texto quando o significado não for óbvio; modo compacto com tooltip acessível.

## 4. Telas (layout sugerido, sem valores fictícios em produção)

- Dashboard: busca universal, estado da plataforma, 4 KPIs, incidentes prioritários, 1 tendência sob demanda.
- OLT/PON: lista à esquerda e painel de detalhes à direita; filtros persistidos por usuário, drill-down sem troca de contexto excessiva.
- ONU/ONT 360: header compacto com serial/status/frescor, abas **Visão geral / Óptica / Cliente / Wi-Fi / Eventos / Ações**; mostrar aba apenas quando a capacidade real existir.
- NOC: fila ordenada por impacto, filtro por cidade/OLT/PON, painel de evidências e ação recomendada.
- Módulos: tabela por nome, estado, versão, latência/heartbeat, causa, dependências e ação autorizada; evitar cards para dezenas de módulos.
- Central de Ajuda: busca, navegação por tarefa/persona e FAQ contextual; passo-a-passo com captura real e callouts pequenos.

## 5. Entregas Lovable e revisão

Gerar telas desktop **1440 × 900** e mobile **390 × 844**, light/dark, com dados sintéticos claramente marcados nos protótipos. Handoff deve conter tokens, componentes, hierarquia, comportamento responsivo, estados edge, acessibilidade, foco e relação tela -> OpenAPI. Claude integra em `apps/web/`, Codex revisa UX e segurança; screenshots finais da documentação são feitos **da aplicação integrada funcionando**, não apenas do mock Lovable.

## 6. Critérios de aceite visual

- Em 5 segundos o usuário identifica o estado da rede, o problema prioritário e a próxima ação.
- Uma tarefa de diagnóstico simples deve ter caminho curto (meta inicial ≤3 interações a partir da busca, excluindo login).
- Nenhum botão de escrita aparece habilitado sem capacidade real e permissão.
- Visualização compreensível sem cor como único indicador; foco e tabulações operam sem mouse.
- Telas não exibem mais de quatro KPIs acima da dobra; dados extras com drilldown.
- Screenshots desktop/mobile + states + manual publicado no mesmo PR da funcionalidade, após integração.
