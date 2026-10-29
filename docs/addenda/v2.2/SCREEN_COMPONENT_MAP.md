# v2.2 — Mapa de telas e componentes (UX_HANDOFF × `apps/web` real)

Navegação (≤6 grupos): **já são 6** (Visão Geral, Rede, Assinantes, NOC, Operações, Administração) — não cresce. Busca universal: ⌘K (`CommandPalette`) + busca por serial no cabeçalho (existem). Link de ajuda contextual: `HelpContextLink` (existe).

## Componentes
| Componente do handoff | Estado | Onde / plano |
|---|---|---|
| AppShell, ThemeToggle, MobileMenu | existe | `components/` |
| GlobalSearch | parcial | ⌘K + busca por serial; falta busca por cliente/contrato (FC22-005) |
| DataFreshness, StatusPill, EmptyState, ErrorState | existe | `components/ui.tsx` |
| EntityDrawer | existe | `EntityDetailDrawer` (dialog modal, foco preso) |
| HelpContextLink | existe | `ui.tsx` |
| SourceChip | falta | FC22-003/005 (fonte + `observed_at` + `quality`) |
| CapabilityGate | falta | **PR 35**: bloco de capacidades no card Ações da ONU 360 |
| ConnectionSummary / OpticalSummary / ClientSummary | parcial | cards Estado/Localização/Assinante da ONU 360 |
| EvidenceTimeline | falta | FC22-007 (Histórico do assinante sem fonte homologada) |
| DiagnosticStepper | falta | FC22-007 |
| IncidentQueue | parcial | lista em `/noc` (sem componente próprio) |
| TopologyTree | falta | FC22-010 |
| ScoreWithCoverage | falta | FC22-011/013 (renderiza `insufficient_data`) |
| ModuleHealthGrid | parcial | tabela em Administração › Módulos |
| ActionPreview | parcial | fluxo de preview/aprovação em Operações |

## Telas
| Tela v2.2 | Estado | Rota atual / alvo | help_slug |
|---|---|---|---|
| Subscriber 360 | parcial | evolui `/rede/onu/[id]` | atual `rede/onu-360`; novo `assinantes/visao-360` quando houver entrada por cliente |
| Guided Troubleshooting | falta | `/assinantes/diagnostico/[id]` (alvo) | `assinantes/diagnostico-guiado` |
| NOC Command Center | parcial | `/noc` evolui | `noc/acompanhar-incidente` (existe) |
| Network Explorer | falta | `/rede/explorar` (alvo) | `rede/explorar-topologia` |
| Wi-Fi Experience | falta/bloqueado | aba de Subscriber 360 | `assinantes/wifi` |
| Automation Studio | falta | `/operacoes` evolui | `operacoes/fluxos` |
| Platform Health | parcial | `/administracao/modulos` | `administracao/saude-modulos` (existe) |

## Regra de entrega por tela (gate do PR)
Estados vazio/carregando/defasado/erro/403; teclado e `axe` sem violação séria (claro/escuro); captura Playwright **real** 1440×900 e 390×844 (`help-screenshots.spec.ts`) com dado sintético; how-to PT-BR + manifesto + `validate_help.py`; parecer Codex. Captura do protótipo Lovable **não** é evidência.
