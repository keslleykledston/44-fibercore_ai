# UX funcional — FiberCore AI

## Princípios

Interface minimalista, alto contraste e **contexto primeiro**. Evitar 20 widgets antes da operação principal. Mostrar dados reais e fonte/frescor, não gráficos artificiais. Ações destrutivas não são botões diretos de 1 clique. Responsiva, teclado/acessibilidade WCAG 2.2 AA como meta.

## Navegação (máximo 6 entradas)

1. Visão Geral: KPI ONUs online/offline/stale, incidentes prioritários, status Edge/GenieACS/USP separado.
2. Rede: OLTs, cards, PON, ONUs; árvore e filtros; detalhamento óptico e ocupação.
3. Assinantes: busca global, vínculo cliente/ONU/CPE, contratos, conflitos e evidências.
4. NOC: incidentes, timeline, causa provável, PON massiva, ação recomendada com fontes.
5. Operações: requisições, approvals, jobs, catálogo templates e changelog.
6. Administração: tenants, roles, conectores, agentes, versões, health dos módulos, integrações ERP/ACS/USP, release canary.

## Telas de entrega (UX-01...08)

**UX-01 Dashboard:** busca global em destaque, prioridade 3 incidentes, 4 KPIs, latência/staleness e status serviços. No máximo um gráfico visível sem expansão.

**UX-02 ONU/CPE 360:** header nome/serial/modelo/status + fonte/time; abas Identidade, Óptica, Cliente, Wi-Fi, Histórico, Operações. Se TR-069 e USP ambos presentes: badge discreto `duas fontes` + comparativo paths por campo. Status ACS control-plane separado do dispositivo.

**UX-03 OLT/PON:** árvore compacta com drilldown, capacidade, status e últimas amostras por janela; seleção múltipla apenas para consulta.

**UX-04 Incident Desk:** lista/timeline, impacto, evidências, próximos passos; indicadores `CONFIRMADO`, `SUSPEITO`, `SEM DADOS` pelo tipo de evidência, não badges coloridos decorativos.

**UX-05 Associação:** busca por contrato/serial/PPPoE; match score justificado e conflitos; edição requer confirmação e histórico.

**UX-06 Operação segura:** wizard seleção de alvo -> capability/diff -> risco/impacto -> aprovação -> confirmação -> execução assíncrona -> pós-check. Progress detalha `queued` vs `verified`.

**UX-07 Module Health:** tabela de módulos, estado, dependências, build, heartbeat, latência, última falha, tenant impactado; toggle feature flag apenas para platform admin com aprovação quando impactar operações.

**UX-08 Release Center:** versões Core/Edge/adapter/driver distintas, changelog, compatibilidade, canary, janela, rollback plan, aprovação de tenant quando aplicável.

## Entregáveis Lovable

- Tokens de cor/tipografia/spacing e componentes shadcn reutilizáveis.
- Vistas desktop 1440 e mobile 390, estados vazio/loading/stale/degraded/error/403 e mock data sintético claramente marcado.
- Componentes com props tipadas e acessibilidade; sem backend próprio de produção, sem usuários fictícios persistidos e sem manipulação de rede.
- Handoff: rotas Next.js, mapa de componentes, estados, eventos, actions e OpenAPI operationId; testes visuais/keyboard.
- Preferir entregar código exportável para `apps/web/` e PR separado de lógica/segurança.
