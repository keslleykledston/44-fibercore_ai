# Normalização de métricas, validade e hipóteses simples

## Contrato de cada medição
`id` (ex.: `ip.rtt_avg_ms`), `group` (WAN/OPTICAL/CORE/INTERNET/ETHERNET/WIFI/CPE), `status`, `value` tipado (number|string|boolean|null), `unit`, `source` (`TR069_READ`, `TR069_ACTIVE`, `OLT_ADAPTER`, `SD001`, `ACS_CACHE`), `path` opcional, `scope` (`SERVICE_WAN`, `MGMT_WAN`, `LAN`, `PON`, `WIFI`), `collectedAt`, `freshnessSec`, `evidenceRef`, `details` seguros.

## Estados SEM zeros falsos
- `valid`: dado normalizado, contemporâneo e relacionado ao objeto correto.
- `stale`: dado anterior ao TTL/ciclo do teste; só exibir como histórico com hora.
- `not_supported`: modelo/firmware homologadamente não expõe a medição.
- `not_available`: recurso esperado, mas sem contato/reachability/medição; não equivale a zero.
- `not_applicable`: não se aplica (ex.: Wi-Fi em ONU bridge sem rádio).
- `failed`: execução falhou e há evidência do erro.
- `inconclusive`: sem prova da execução atual, contador parcial/inconsistente, origem equivocada.

## TTLs iniciais SUGERIDOS (ajustar à coleta real, sem polling extra)
| Grupo | Frescor UI | Observação |
|---|---|---|
| WAN / PPPoE / link Ethernet | 15 min | Estado pode mudar antes; carimbar horário |
| Óptica / PON | 15 min | Priorizar dados monitorados existentes, se houver |
| Wi-Fi associados/PHY | 5 min | Mudanças frequentes; evitar varredura contínua |
| CPU / memória | 5 min | Somente se suportado e coleta barata |
| Inventário / firmware | 24 h | Alteração firmware invalida capability cache |
| Ping / DNS / traceroute | Somente run específico | Não reutilizar `Complete` antigo em run novo |
| SD-001 Speed | Somente run específico | Delegar validade ao SD-001 |

**Frescor é atributo exibido, NÃO um gatilho automático para consultar toda a árvore ACS.** Evitar sobrecarga em CPE/ACS. `ACS_CACHE` nunca deve ser falsamente tratado como leitura em tempo real.

## Fórmulas e limites
- Perda ICMP `% = 100 * FailureCount / (SuccessCount + FailureCount)` quando repetição completa e contagens válidas; exibir tamanho da amostra. Se zero tentativas, `inconclusive`.
- RTT mínimo/médio/máximo em ms segundo fonte; não usar `(max-min)` como jitter técnico.
- DNS: tempo por lookup fornecido pelo objeto quando houver; não estimar pela latência de tarefa ACS.
- Link Ethernet negociado `100 Mbps` pode limitar tráfego naquela porta, mas não prova que plano não chega à ONT.
- Contadores de erro: calcular DELTA com duas leituras válidas; após reboot/rollover/reset, invalidar delta. Apenas valor acumulado não comprova piora recente.
- `OpticalSignalLevel`: dividir por 1000 **somente** para campo TR-181 oficial. Para vendor específico, unidade/escala por capability profile. Sem limite dBm genérico global.
- `CPUUsage` alto durante teste pode ser consequência da carga, não causa comprovada do gargalo; mencionar contexto.

## Motor de hipóteses P0 (regras declarativas e transparentes)
Cada hipótese inclui `code`, `label`, `confidence` (`low`/`medium`), `evidenceMetricIds[]`, `recommendedCheck`, `caveats[]`. Nenhuma mudança de configuração automática.

| Código | Evidência mínima | Texto de hipótese (nunca afirmação final) |
|---|---|---|
| `LAN_LINK_100M` | LAN com `link_speed_mbps=100` + plano conhecido >100 Mbps **ou** relato de problema na porta | "Porta LAN pode limitar a conexão deste dispositivo; verificar cabeamento/equipamento" |
| `WIFI_POTENTIAL` | Sinal ruim conforme perfil homologado + retries/drops aumentados (ou taxa PHY baixa) | "Possível limitação de Wi-Fi; testar dispositivo cabeado" |
| `OPTICAL_ATTENTION` | Sinal fora da faixa homologada ou alarmes/erros PON correlatos | "Indícios de problema no enlace óptico; validar OLT e conectorização" |
| `EXTERNAL_PATH_POTENTIAL` | SD-001 Core válido e desempenho externo degradado em teste comparável + servidor externo saudável | "Possível gargalo em trânsito/rota/destino; validar caminho externo" |
| `ACCESS_PATH_POTENTIAL` | Core + Internet degradados em medições comparáveis, e indicação de limitações descartadas | "Possível gargalo no acesso/BNG/CPE; investigar policer, CPU e PON" |
| `DNS_POTENTIAL` | DNS com erros/lentidão e ping IP válido em mesmo período | "Possível falha de resolução DNS; testar resolutores" |
| `PACKET_LOSS` | Falha em ping com amostra válida e destino confiável | "Perda observada para o destino medido; comparar com outro alvo" |

**Sem dados suficientes:** mostrar `sem evidência suficiente para localizar gargalo`, com os testes necessários para avançar. Não retornar uma hipótese só para preencher a UI.

## Regras anti-falso diagnóstico
- Um destino externo ruim não prova problema de trânsito: verificar endpoint e rota, carga do servidor, horários e testes comparáveis.
- Só uma amostra de RX não prova rompimento; cada modelo/classe óptica tem faixas diferentes.
- Wi-Fi PHY ≠ tráfego útil; RSSI não informa sozinho saturação/canal.
- Diagnóstico de ONT em bridge usando VLAN de gestão não representa banda do assinante.
- Exibir "medida originada na ONT" sempre que se referir a ping ou throughput na WAN, e fonte da OLT quando aplicável.
