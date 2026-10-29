# UX Handoff — mínimo, futurista, estilo iOS original K3G

**Domínio:** fibercore.devops.k3gsolutions.com.br.  **Ajuda:** `/ajuda`. Desktop-first, mobile útil, acessível.

## Navegação (até 6)
Visão Geral | Rede | Assinantes | NOC | Operações | Administração. Busca universal no topo e link contextual de Ajuda; cada persona vê apenas capacidades autorizadas.

## Componentes principais
`AppShell`, `GlobalSearch`, `ContextHeader`, `DataFreshness`, `SourceChip`, `StatusPill`, `EntityDrawer`, `EvidenceTimeline`, `OpticalSummary`, `ConnectionSummary`, `ClientSummary`, `CapabilityGate`, `DiagnosticStepper`, `IncidentQueue`, `TopologyTree`, `ScoreWithCoverage`, `ModuleHealthGrid`, `ActionPreview`, `HelpContextLink`.

## Telas
**Subscriber 360:** resumo compacto fixo (cliente/serial/status/proveniência), abas `Conexão | Óptica | Wi-Fi | Cliente | Histórico | Ações`; escolher só abas suportadas. Não mostrar senha. Fluxo: busca universal → abrir detalhe → sugestão contextual.

**Guided Troubleshooting:** coluna passos/checks e painel evidências; 1 ação por etapa; rotular `confirmado`, `hipótese`, `indisponível`. Botão 'gerar resumo para ticket' sem alterar rede.

**NOC Command Center:** prioridades e incidência coletiva com lista filtrável. KPIs máximos 4; abrir incidente em drawer em vez de trocar tela; correlacionar com saúde Edge.

**Network Explorer:** drilldown POP/OLT/PON/CTO/ONU, árvore ou lista; mapa apenas opcional; relações não confirmadas recebem ícone de 'pendente de validação'.

**Wi-Fi Experience:** qualidade/sinais/banda/clientes somente quando device capability observada; 'dados insuficientes' em vez de score falso; sugerir leitura e escalonamento.

**Automation Studio:** catálogo de service intents e visual de fluxo por passos, sem editor arbitrário de shell; dry-run, diff, risco, aprovação e pós-check; nunca pular workflow engine.

**Platform Health:** módulos/conectores/versões, causa degradada, dependências; falha opcional não derruba navegação.

## Critérios visuais
UI clean, alto contraste, whitespace controlado, bordas suaves e animações 120–220ms, `prefers-reduced-motion`, tema dark/light, navegação por teclado, estados error/loading/stale/empty/403. No máximo 4 KPIs e um gráfico inicial; dados técnicos profundos são revelados sob demanda. Não copiar fontes SF, gráficos ou UI de concorrentes.

## Handoff para implementação
Para cada tela entregar: frame 1440×900 e 390×844, estados, componentes exportáveis Next.js TS/shadcn, tokens, rotas/operationIds, `help_slug`, microcopy PT-BR, passos de ajuda, fixtures sintéticas. Screenshots finais dos how-to serão produzidos pelo Claude com Playwright na aplicação real, não a partir do protótipo do Lovable.
