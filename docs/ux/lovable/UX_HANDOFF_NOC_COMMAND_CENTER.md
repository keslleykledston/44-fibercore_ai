# Handoff de UX — NOC Command Center (FC22-009)

Terceiro lote ao Lovable (dados sintéticos, sem segredos). Referência visual apenas.

## Objetivo
Evoluir `/noc`: fila priorizada de incidentes com **impacto** (clientes afetados, com fonte) e **no máximo 4 KPIs**; abrir o incidente em **drawer** (painel lateral; em mobile, folha inferior) em vez de trocar de tela; correlacionar com a saúde dos Edges. Minimalista, estilo iOS, claro/escuro, pt-BR, WCAG 2.2 AA, alvos ≥ 44 px.

## Regras
- KPIs (máx. 4): incidentes abertos; não reconhecidos; clientes afetados (distintos, via associações aprovadas, com a fonte); Edges silenciosos.
- Ordem da fila (explicável, sem score): abertos primeiro; não reconhecidos antes; queda confirmada antes de "Edge silencioso"; maior impacto (clientes afetados; "indisponível" por último); mais ONUs fora; mais recente.
- Edge silencioso ≠ ONUs offline: o incidente atrás dele é "último estado conhecido".
- Causa é hipótese ("não é diagnóstico"). Impacto indisponível (papel sem acesso a clientes) aparece como "Impacto indisponível para o seu papel", nunca como zero.
- Drawer: evidências (ONUs fora/observadas, LOS, energia, crônicas), impacto + fonte, ONUs do incidente (serial, status; link "Abrir ONU 360"), idade dos dados. Fecha com Esc e devolve o foco. Nenhuma ação de escrita na rede.

## Estados
Fila normal; vazia; carregando; erro; Edge silencioso com incidente suprimido; impacto indisponível; filtro "só não reconhecidos"; drawer aberto; desktop 1440×900 e mobile 390×844; claro e escuro.
