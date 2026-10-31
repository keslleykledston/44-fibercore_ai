# QoS-001 — GAP_MAP (só o que falta; o resto é reaproveitado)

Classificação: **JÁ** = implementado, reutilizar sem mudança · **ESTENDER** = menor extensão de componente existente · **BLOQUEADO** = depende de decisão/evidência que não existe · **FORA** = fora do escopo do adendo ou deste lote.

## A. Leituras (RÁPIDO, passivas)
| # | Requisito do adendo | Classe | Evidência / o que fazer |
|---|---|---|---|
| A1 | Estado WAN / PPPoE / uptime | **JÁ** | `cpe_state`: `wan_link_status`, `wan_connection_status`, `uptime_seconds` (ADR-SD-002, `app/api/cpe_state.py:34`) |
| A2 | Rotular WAN de **serviço** × gestão | **BLOQUEADO** fora da bancada | só existe `speed_wan_interface` na config local do Edge (um dispositivo). Sem isso a UI mostra a telemetria com escopo "WAN não classificada" e **não** atribui nada ao serviço (Q03). Decisão: ADR do responsável sobre como identificar a WAN de serviço por modelo (registro de capacidades) |
| A3 | Endereço IPv4/IPv6 | **FORA** | texto livre/PII; ADR-SD-002 proíbe. No máximo `ip_family_present` (enum) em P1 |
| A4 | Óptica / PON | **JÁ** (origem **OLT**) | `onus.rx_dbm`, `onu_state_events`; fonte `OLT_ADAPTER`; nunca `TR069_READ` (Q12). Óptica por TR-069 (`Device.Optical`): **BLOQUEADO** (sem caminho/escala validados por modelo) |
| A5 | Ethernet: status do enlace e velocidade negociada | **ESTENDER** | acrescentar 2 métricas fechadas ao `cpe_state` (`eth_link_status`, `eth_link_speed_mbps`) — lista fechada em `params.go` + `cpe_state.py` + CHECK do banco + teste cruzado Go↔API |
| A6 | Ethernet: erros/descartes (delta) | **ESTENDER P1** | contadores brutos + delta só entre duas leituras válidas, reset/reboot invalida (Q13). Lote 2 |
| A7 | Wi-Fi rádio/canal | **JÁ** | `wifi_radio_enabled`, `wifi_channel` |
| A8 | Wi-Fi retries/PHY/RSSI/associados | **FORA** deste lote | exige enumerar `AssociatedDevice` (MAC/PII); ADR-SD-002 item 5 |
| A9 | CPU/memória | **ESTENDER P1** | opcional, só se o perfil do modelo expuser; sem PII. Lote 2 |
| A10 | Frescor por grupo e "sem zero falso" | **ESTENDER** | `DISPLAY_FRESH_FOR` já é só dica; faltam TTLs por grupo e estados `valid|stale|not_supported|not_available|not_applicable|failed|inconclusive` em função pura nova (`app/core/quality.py`) |

## B. Testes ativos (RÁPIDO) — escrevem `DiagnosticsState` no CPE
| # | Requisito | Classe | Evidência / o que fazer |
|---|---|---|---|
| B1 | `IPPing` (poucos pacotes, destino aprovado) | **ESTENDER** + **BLOQUEADO** p/ produção | novo item no catálogo de bancada (`BENCH_OPS`, mesmo padrão de `speed_test_*`), **precedido da emenda ao ADR-0030** (a lista é fechada e só muda por emenda, com parâmetros, autorização e evidência definidos), Edge: um `setParameterValues` com `Interface`+`Host`+`NumberOfRepetitions`+`Timeout`+`DiagnosticsState`, polling com prova de frescor (mesmo desenho de `internal/nbi/speed.go`). Fora de bancada continua bloqueado por `HOMOLOGATED_WRITES` vazio — decisão do responsável (item 1 do plano) |
| B2 | `NSLookup` (hostname cadastrado) | **ESTENDER** + **BLOQUEADO** idem | idem; hostname só por id lógico, nome real na config local do Edge |
| B3 | Traceroute opcional | **FORA** deste lote | P1, exige homologação própria por firmware; entra depois dos dois acima |
| B4 | Destinos aprovados, sem SSRF | **ESTENDER** | reutiliza o catálogo lógico (`speed_endpoints` + config local do Edge, `internal/speed` validações). DNS exige um tipo de destino novo (`target_kind = DNS`): migração aditiva com CHECK ampliado |
| B5 | Lock por CPE: um `DiagnosticsState` por vez, 1 job ativo, limites PON/provedor | **ESTENDER (NÃO é reaproveitamento direto)** | `busy_reason()` (`app/core/speed.py:142`) hoje consulta **só** `speed_test_runs`: ele NÃO enxerga ping/DNS, então hoje uma suite de qualidade e um teste de banda poderiam disputar o `DiagnosticsState` do mesmo CPE. Entrega obrigatória do PR A: uma reserva compartilhada por CPE para toda operação que escreve diagnóstico (banda, ping, DNS), tomada sob o mesmo lock consultivo e liberada em estado terminal, incluindo jobs ainda pendentes; teste que prova a recusa nos dois sentidos (banda→ping e ping→banda) e a serialização sob concorrência |
| B6 | NBI 200/202 ≠ concluído; sem `Complete` antigo | **JÁ** (speed) → **ESTENDER** | padrão do Edge: lê o estado antes, ignora resultado velho, 202 ⇒ remove a própria tarefa e não reenvia |
| B7 | Falha parcial não derruba o resto | **ESTENDER** | estados de suite `completed|partial|failed|timeout` |

## C. COMPLETO e orquestração
| # | Requisito | Classe | Evidência / o que fazer |
|---|---|---|---|
| C1 | Reusar SD-001, **sem segundo motor TR-143** | **JÁ** | `POST /v1/cpes/{id}/speed/runs`; o QoS só guarda `speed_run_group_id` |
| C2 | Banda executável hoje | **BLOQUEADO** | gate `redirect_unverified` (EG8145V5 segue 3xx): precisa de ACL de saída real ou emenda do ADR-0038; COMPLETO mostra `speed=not_available` e preserva a parte rápida (Q10) |
| C3 | Entidade de suite (`QualityRun`) | **ESTENDER — PROPOSTA, condicionada ao ADR-0039** (o ADR pode alterar ou rejeitar) | `quality_runs` (RLS forçada, imutável como `diagnostic_jobs`): modo, estado, métricas normalizadas, hipóteses, ids de jobs e do grupo de speed |
| C4 | API | **ESTENDER — PROPOSTA, condicionada ao ADR-0039** | `POST/GET /v1/cpes/{id}/quality/runs` no mesmo estilo de `app/api/speed.py`; **sem** endpoint genérico duplicado |
| C5 | Sem nova fila/worker/broker | **JÁ** | usa os jobs assinados e o outbox atuais |

## D. Interpretação
| # | Requisito | Classe | Evidência / o que fazer |
|---|---|---|---|
| D1 | Hipóteses determinísticas, com ids de métrica e ressalvas | **ESTENDER** | regras puras em `app/core/quality.py` (LAN_LINK_100M, WIFI_POTENTIAL só se houver dados, OPTICAL_ATTENTION por perfil, EXTERNAL_PATH/ACCESS_PATH só com SD-001 válido, DNS_POTENTIAL, PACKET_LOSS); sem score; "dados insuficientes" é saída legítima |
| D2 | Copiloto read-only | **BLOQUEADO** | `smart_diagnostics_copilot` bloqueada até ADR-0015/SD-006; este lote só deixa o JSON normalizado pronto para ele |
| D3 | Plano contratado × medido | **FORA** | só com fonte já integrada (ERP); nenhuma conclusão de SLA |

## E. Governança, UX, evidência
| # | Requisito | Classe | O que fazer |
|---|---|---|---|
| E1 | Flags independentes, OFF | **ESTENDER** | `quality_diagnostics`, `quality_active_tests`, `quality_full` (`app/core/features.py`); desligar QoS não afeta SD-001 (Q19) |
| E2 | RBAC e auditoria | **ESTENDER** | `diagnostics:quality_read`, `diagnostics:quality_run`, `diagnostics:quality_run_full` (+ matriz regenerada); `quality.requested|blocked` na auditoria; COMPLETO exige também `diagnostics:speed_run` |
| E3 | Cartão no sidebar existente | **ESTENDER** | nova aba "Qualidade" em `OnuQuickInspector.tsx` + cartão no ONU 360, no padrão de `SpeedTestSection.tsx`; 4 indicadores + "Ver detalhes por camada"; **sem nova página** |
| E4 | Central de Ajuda com capturas reais | **ESTENDER** | `docs/help/how-to/rede/qualidade-do-servico.md`, manifesto, `e2e/help-quality.spec.ts`; estados simulados rotulados como cenário |
| E5 | Changelog / ADR / homologação multivendor | **ESTENDER** | ADR-0039; `docs/operations/QUALITY_HOMOLOGACAO.md` (planilha por modelo/firmware, vazia até haver execução real) |
| E6 | Homologação multivendor | **BLOQUEADO** (autorização) | EG8145V5 (lido, ver H-speed-sonda), ZTE F670L e Nokia G-1426G-A (H1 só leitura, sem vínculo confirmado na ZTE, fora da lista de bancada). Execução real exige a autorização do responsável por identidade e por manobra |
| E7 | TR-369, auto-remediação, iperf/TR-471, score, varredura | **FORA** | explícito no adendo |
