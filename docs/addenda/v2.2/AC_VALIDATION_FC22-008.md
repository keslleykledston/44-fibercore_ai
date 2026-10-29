# FC22-008 — Validação de AC-004 (frescor) e AC-009 (NOC) contra o código

Data: 2026-10-29 · Escopo: **só validar e documentar** o que já existe (ADR-0018, `edge_silent`, `incident_onus`); nenhum comportamento foi alterado. Cada linha aponta um teste que roda na suíte (`pytest -q`, 240 passed no commit desta validação).

## AC-004 — Edge offline ⇒ stale/unknown; nunca "ONU offline generalizada"
| Caso | Teste | O que prova |
|---|---|---|
| Silêncio do Edge não vira ONU offline | `test_inventory.py::test_silence_means_stale_not_offline` | leitura de ONU/OLT sem coleta recente é `stale`, com idade; o status gravado não muda |
| Heartbeat velho lê offline do **Edge**, não das ONUs | `test_edge.py::test_stale_heartbeat_reads_offline_not_online` | o estado "offline" é do coletor |
| Incidente aberto + Edge silencioso | `test_noc.py::test_silent_edge_flags_incidents_and_never_fabricates_offline` | incidente é marcado `edge_silent` (suprimido) e o Edge aparece como alerta; nenhuma ONU é inventada offline |
| Snapshot velho (>15 min) nunca ABRE incidente | `test_noc.py::test_backlogged_old_snapshots_never_open_an_incident`, `test_a_drop_that_already_ended_in_the_backlog_does_not_open_either`, `test_ongoing_outage_discovered_after_a_backlog_opens_on_the_fresh_snapshot` | backlog atualiza o histórico; só o snapshot fresco avalia |
| Snapshot velho e saudável nunca FECHA incidente aberto | `test_noc.py::test_an_old_all_healthy_snapshot_never_resolves_an_open_incident` | **teste novo** (a primeira versão desta matriz citou, por engano, `test_stale_snapshot_data_does_not_count_toward_current_state`, que só prova que amostra PARCIAL não resolve; Codex apontou). Mutante sem o gate `EVAL_FRESH_FOR` reprova |
| Amostra parcial não fecha incidente | `test_noc.py::test_stale_snapshot_data_does_not_count_toward_current_state` | evidência insuficiente (2 de 10 ONUs reportadas) não resolve |
| Silêncio nunca expira nem resolve incidente | `test_noc.py::test_silence_never_expires_an_incident` | ausência de dado não é evidência de recuperação |
| Queda ocorrida durante o silêncio ainda é detectada ao voltar | `test_noc.py::test_outage_while_the_edge_was_silent_is_still_detected` | janela de 6 h (ADR-0018) |
| Contagens da PON carregam a idade | `test_onu360.py::test_pon_counts_carry_their_age_so_stale_is_not_shown_as_current` | "13 online de 15" vem com a idade, não como estado atual |
| Diagnóstico com dado velho = `unknown` | `test_inventory_diagnostics.py::test_stale_data_is_unknown_never_a_claim` | R-D001 não afirma nada com dado velho |
| Contexto do cliente com OLT velha = `stale` por bloco | `test_inventory_context.py::test_old_olt_snapshot_makes_the_context_stale_and_never_reads_as_a_fresh_or_offline_claim` | **teste novo desta validação**: só o bloco velho é velho; ERP fresco continua fresco |

## AC-009 — incidentes massivos correlacionados sem duplicar todos os clientes
| Caso | Teste / fato de projeto | O que prova |
|---|---|---|
| Um incidente por PON, deduplicado | `test_noc.py::test_mass_outage_opens_once_dedupes_and_resolves_with_hysteresis`; índice único parcial por PON aberta | queda de N ONUs = 1 incidente, histerese na resolução |
| Concorrência não duplica | `test_noc.py::test_concurrent_drop_snapshots_open_a_single_incident` | duas ingestões simultâneas abrem 1 |
| ONUs são membros, não incidentes | tabela `incidents` sem coluna de cliente; `incident_onus` guarda as ONUs | clientes derivam do vínculo aprovado; nenhum incidente por cliente |
| Quedas crônicas não diluem nem inflam | `test_noc.py::test_chronic_offline_do_not_dilute_a_real_drop_and_are_reported` | frota crônica fica fora do numerador e do denominador e é reportada |
| Quem cai depois entra no mesmo incidente | `test_noc.py::test_onus_dropping_after_the_incident_opened_join_it` | cresce o incidente, não cria outro |
| RBAC e isolamento | `test_noc.py::test_rbac_ack_and_tenant_isolation` | A não vê B; ack exige permissão |

## Lacunas declaradas (não são ocultadas)
- **R-D003 explícita** ("Edge unreachable ⇒ incidente da infraestrutura de coleta, não dezenas de ONU offline"): o **comportamento** existe (`edge_silent` + alerta do Edge, linhas acima) mas **não** como regra versionada no motor (ADR-0024). Transformá-la em regra é trabalho futuro sem mudar o comportamento.
- **R-D004** (ONU online na óptica, CPE sem Inform recente): precisa de sessão ACS/CWMP por CPE, que o Edge ainda não coleta. Não implementada.
- **Impacto ("clientes afetados")** por incidente não é exposto: é o escopo do FC22-009.
- **Carga/p95** (AC-018) não medidos.
