# Proposta de UX do Lovable (DEMO) — referência de revisão

- Projeto Lovable: `13aaf09e-023f-464e-8651-190d6d928dfc` (workspace do proprietário; preview: https://id-preview--13aaf09e-023f-464e-8651-190d6d928dfc.lovable.app). Commit da proposta: `dcdc11d82b951ce0c76a313108e844b6308f6134`. Custo: 18,8 créditos.
- Escopo recebido: 9 telas (Login/workspace, Visão Geral, Rede, ONU 360, NOC, Assinantes, Operações, Módulos, Ajuda), tema claro/escuro, seletor global de estado DEMO (normal/carregando/vazio/defasado/erro/403), componentes `AppShell`, `GlobalSearch (⌘K)`, `StateGate`, `WriteActionButton` (sempre bloqueado com motivo "Operação não homologada"), `ApprovalTimeline`, `IncidentQueue`, `ModuleHealthTable`, etc. Documento do Lovable: `docs/UX-PROPOSTA.md` no projeto deles.
- **Verificação do próprio Lovable:** só Visão Geral, Rede, NOC e Operações (desktop/mobile) e busca Ctrl+K; **tema escuro, demais telas, estados alternativos e WCAG AA NÃO verificados** — nada disso foi aceito por nós como evidência.
- Nada do código Lovable foi importado ao repositório (é uma proposta; screenshots finais vêm da aplicação integrada).

## Decisões de integração
| Item da proposta | Decisão |
|---|---|
| Ordenação da fila NOC por (não reconhecido, severidade, impacto); edge silencioso nunca acima de queda crítica | **Adotado** em `apps/web/src/app/noc/page.tsx` |
| Edge silencioso ≠ offline; "último estado conhecido" | Já implementado (E2E cobre) |
| Escrita sempre bloqueada com motivo visível | Adotar nas telas de Operações/ONU 360 (W8) |
| ⌘/Ctrl+K busca global | **Adotado** (`CommandPalette`: telas + atalho "Buscar ONU" → `/rede?serial=`; sem chamada de API própria; `<dialog>` nativo com foco preso e Esc) |
| ONU 360, Assinantes, Operações, Login multi-passo | Pendentes (W8); usar a proposta como referência visual |
| Seletor de estado DEMO | Não adotar em produção (somente fixture de teste) |

## Revisão visual aplicada (2026-10-28, branch `web/17-visual-review`)
Adotado da proposta, adaptado aos tokens já validados por axe (os valores de `muted`/`accent` do repositório foram mantidos por contraste; os do Lovable não foram medidos por eles):
- Tokens de severidade suave (`ok/warn/danger/stale/accent-soft`), `surface-2`, sombra de card, transição de 180 ms com `prefers-reduced-motion` respeitado.
- `StatusPill` em pílula com fundo suave — texto e símbolo continuam (cor nunca é o único indicador).
- `Kpi` sem caixa-alta, números tabulares.
- `AppShell`: ícones, item ativo em `accent-soft`, barra superior fixa, menu mobile em gaveta (`MobileMenu`), alternância manual de tema claro/escuro persistida em `localStorage` (convenience; sem ela vale `prefers-color-scheme`).
- Não adotado ainda: ONU 360, Login multi-passo, `EntityDetailDrawer`, grade virtualizada (dependem de API/telas novas — W8).

## Visão 360 do assinante (2026-10-29, FC22-005)
- **Um** pedido em lote (`UX_HANDOFF_SUBSCRIBER_360.md`, dados sintéticos, sem segredos) ao projeto acima; commit `1ad87e8a8d69…`. A chamada MCP estourou o timeout ocioso (300 s) mas o agente concluiu; o resultado foi lido por `read_file`. Nada do código foi importado.
- **Adotado:** "Cobertura das informações" com estado em texto + ícone e a frase do porquê; rótulo "Último estado conhecido" + "a idade do dado não indica ONU offline"; aba Conexão agrupando conexão + roteador + incidente; abas Óptica/Roteador só com dado; "Não é diagnóstico" no incidente; mensagens de erro/403 que não afirmam nada.
- **Não adotado:** skeleton de carregamento via `loading.tsx` (faz o Next responder 200 para `notFound`); seletor de estado de demonstração; abas por JS (as nossas são links de servidor, funcionam sem hidratação); botões Confirmar/Rejeitar na tela do cliente (a revisão fica na ONU 360).
- **Não verificado por nós no Lovable:** tema escuro e demais estados da página de demonstração.
## Diagnóstico guiado (2026-10-29, FC22-007)
- Segundo e último lote desta fase (`UX_HANDOFF_GUIDED_TROUBLESHOOTING.md`), commit `151f59d74fc1…`, 4,7 créditos, concluído (chamada com `wait=false`; resultado lido por `get_message`/`read_file`). Nada do código foi importado.
- **Adotado:** rótulos de confiança Confirmado/Hipótese/Indisponível em texto+símbolo; as frases de cautela por passo ("não comprova conexão", "Rx ausente não comprova a causa da queda", "identificar o roteador não comprova acesso à internet"); ticket com "Sintoma relatado" e a idade de cada fonte em minutos; nenhum botão de escrita.
- **Não adotado:** seletor de estado DEMO; estado de permissão simulado por flag no cliente (aqui a permissão vem do servidor: 403 do BFF); dados fixos de PON (aqui vêm do `diagnostic_runs`).
- **Não verificado por nós no Lovable:** tema escuro e demais estados da página de demonstração.
## NOC Command Center (2026-10-29, FC22-009)
- Terceiro lote (`UX_HANDOFF_NOC_COMMAND_CENTER.md`), commit `c9772843c4fa…`, 5,2 créditos, concluído. Nada do código foi importado.
- **Adotado:** exatamente 4 KPIs; ordem de fila explicável (sem score); impacto = clientes distintos por associações aprovadas, nunca 0 quando indisponível; **incidentes atrás de Edge silencioso ficam fora do impacto atual** (aqui continuam na fila, por último, e contados à parte em `open_suppressed`); drawer lateral com Esc/foco; causa como hipótese.
- **Não adotado:** seletor de cenários DEMO; incidentes suprimidos fora da fila (preferimos listá-los, marcados e ordenados por último, para não esconder um incidente aberto); folha inferior no mobile (o painel lateral do `<dialog>` já cobre a largura total no celular).
- **Não verificado por nós no Lovable:** tema escuro e demais estados da página de demonstração.
