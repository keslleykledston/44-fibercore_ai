# Plano de qualidade — Quick Inspector

| ID | Cenário | Esperado |
|---|---|---|
| Q01 | selecionar ONU na lista | painel abre; seleção visível; lista/filtros preservados |
| Q02 | trocar A -> B -> C rapidamente | só C; requests antigos ignorados/cancelados |
| Q03 | fechar via X / ESC | fecha; foco retorna; sem perda de filtros |
| Q04 | PON online + ACS stale | PON registrada + ACS sem contato; não offline |
| Q05 | Edge OLT fora + ACS recente | `Coleta OLT indisponível`; não assumir PON offline |
| Q06 | RX null | `RX não disponível`; sem 0 dBm |
| Q07 | óptica atenção de policy | severidade derivada de regras homologadas |
| Q08 | vínculo baixa confiança | não exibir como cliente confirmado |
| Q09 | PII bloqueada por RBAC | nome/contrato ocultos; cache isolado |
| Q10 | tenant cruzado | 403/404 sanitizado; sem dados de outro ISP |
| Q11 | modelo desconhecido | SVG genérico, texto explícito; sem LEDs fictícios |
| Q12 | erro parcial ACS/ERP | dados OLT ainda exibidos |
| Q13 | responsive 1440/1024/390 | sem horizontal scroll; drawer correto |
| Q14 | keyboard e reduced motion | tab order, ESC, foco, animação reduzida |
| Q15 | botão ONU 360° | rota real e retorno contextual seguro |
| Q16 | feature flag OFF | UI original sem regressão |
| Q17 | IA/Investigação indisponível | CTA oculto/desabilitado explicativamente conforme DS, sem chamar mock |
| Q18 | fonte e freshness | times corretos por fonte e indicação stale |
| Q19 | 200% zoom | legibilidade e botões visíveis |
| Q20 | docs | screenshot da app real, how-to e manifest atualizados |

### Pirâmide
- Unit: selectors, formatação, RBAC display gates, stale logic via backend, template generic.
- Component: painel keyboard, troca seleção, erro parcial, skeleton/empty, links.
- Integration: auth, RLS tenant A/B, fontes concorrentes, contratualidade.
- E2E: 1440x900 e 390x844 light/dark, foco, navegação, preservação filtros.
- Performance: selecionar 100x em lista virtualizada sem duplicar subscriptions; sem re-render de 10k ONUs ao alterar uma seleção.
