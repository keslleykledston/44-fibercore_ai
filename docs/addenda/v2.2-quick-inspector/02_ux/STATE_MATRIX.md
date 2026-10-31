# Matriz de estados — não confundir fontes

| Fonte | Estado bruto | Rótulo recomendado | Visual | Animação |
|---|---|---|---|---|
| OLT/PON | online (fresco) | `PON registrada` | verde discreto | pulso opcional 1 vez na transição |
| OLT/PON | offline (fresco) | `PON offline` | vermelho só se observado | nenhuma obrigatória |
| OLT/PON | unknown | `Estado PON desconhecido` | neutro/cinza | nenhuma |
| OLT/PON | stale | `PON: dados defasados` | neutro + ícone relógio | nenhuma |
| OLT/driver | unavailable | `Coleta OLT indisponível` | neutro + alerta textual | nenhuma |
| ACS | connected | `ACS comunicando` | verde discreto | nenhuma |
| ACS | stale | `ACS sem contato recente` | âmbar informativo | nenhuma |
| ACS | unavailable | `Conector ACS indisponível` | neutro + texto | nenhuma |
| ACS | unsupported | `ACS não disponível para este modelo` | neutro | nenhuma |
| Óptica | observed+within-policy | `RX -x,x dBm` | texto neutro | nenhuma |
| Óptica | observed+warning (policy) | `Atenção óptica` | âmbar | glow suave opcional |
| Óptica | observed+critical (policy) | `Sinal crítico` | vermelho | pulso discreto opcional |
| Óptica | unavailable | `RX não disponível` | neutro | nenhuma |
| ERP | unassociated | `Sem cliente associado` | neutro | nenhuma |
| ERP | conflict | `Vínculo em conflito` | âmbar + texto | nenhuma |
| ERP | missing permission | `Dados do cliente restritos` | neutro | nenhuma |
| Pending jobs | queued | `Aguardando execução` | informativo | **não** sucesso |

**Nunca:** ACS sem contato => ONU offline; loss of access to connector => LOS; `null` RX => 0 dBm; associação fraca => cliente confirmado; status `unknown` => down.

`observed_at` (medição no equipamento) é distinto de `collected_at` (ingestão no FiberCore). Políticas TTL são configuráveis por métrica/source; em preview apenas simuladas. `is_stale` deve vir de política validada; exibir o tempo e fonte.
