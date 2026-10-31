# Homologação por fabricante/modelo/firmware — roteiro reutilizável

## Ficha de homologação (preencher com evidências reais)
- Tenant/ambiente: ___ | Fabricante/OUI: ___ | Modelo: ___ | Hardware: ___ | Firmware: ___
- Modo: roteado/bridge/híbrido: ___ | WAN serviço validada: ___ | WAN gestão: ___ | PON/OLT/porta: ___
- Modelo de dados: Device:2 / IGD:1 / vendor: ___ | Último Inform: ___
- Ping: suportado? `Requested→Complete`? dados novos? interface correta?: ___
- DNS: suportado? `Result` completo? tempo medido?: ___
- Traceroute: suportado? seguro?: ___
- RX PON: caminho, escala/unidade, validação OLT?: ___
- Ethernet: velocidade, erros, reset de contadores?: ___
- Wi-Fi: RSSI/PHY/retries/canal, exposição de PII?: ___
- CPU/memória/uptime: dados válidos? ___
- SD-001 Core / Internet: `speedRunId` comprovado? ___
- Escopo homologado: RÁPIDO / COMPLETO / somente telemetria ___
- Evidências: logs saneados, parâmetros, timestamps, screenshots reais, testes e responsável: ___

## Cenários de aceite obrigatórios
| ID | Dado/Cenário | Resultado esperado |
|---|---|---|
| Q01 | ONT roteada, Device:2, ping/DNS válidos | RÁPIDO retorna RTT/perda/DNS com hora e origem |
| Q02 | ONT TR-098 | Mapeamento IGD, sem path Device:2 hardcoded |
| Q03 | ONU em bridge e ACS só em gestão | Não atribuir ping/throughput ao serviço de cliente; telemetria rotulada |
| Q04 | ONT sem DNS ou Wi-Fi | `not_supported`/`not_applicable`, sem zeros falsos |
| Q05 | ACS com `Complete` de ontem | Não aceitar como teste de agora; `stale`/`inconclusive` |
| Q06 | GenieACS HTTP 202 task queued | UI mostra fila, NÃO sucesso de teste |
| Q07 | Inform atrasado ou do outro diagnóstico | Não vincular resultados a suite atual sem correlação |
| Q08 | Acesso Viewer / outra tenant | Nega execução e vazamento de histórico/PII |
| Q09 | Diagnóstico completo com speed SD-001 já executando | Compartilha controle de concorrência; não duplica run |
| Q10 | SD-001 incompatível, leituras básicas válidas | COMPLETO parcial com telemetria preservada |
| Q11 | Ethernet 100 Mbps | Hipótese, não classificação automática do plano todo |
| Q12 | Óptica origem OLT, fora da faixa por classe | Fonte `OLT_ADAPTER`, limiar por perfil, não `TR069_READ` |
| Q13 | Contador reseta durante janela | Invalidar delta de erros/descartes |
| Q14 | Firmware alterado | Invalidar capability de escrita/homologação anterior |
| Q15 | NBI indisponível | UI e aplicações principais continuam íntegros |
| Q16 | Tudo indisponível | `Dados insuficientes`, jamais qualidade OK |
| Q17 | CORE bom / INTERNET ruim com servidor sobrecarregado | Hipótese externa não conclusiva; validar destino |
| Q18 | Teste autorizado e trilha de auditoria | Contém ator, tenant, device, job, hora, tipo; nenhum segredo |
| Q19 | Cortar feature flag | QoS some/desativa; SD-001 e provisionamento seguem intactos |
| Q20 | Smartphone Wi-Fi fraco, WAN ONT boa | Declarar que ONT não mede performance end-to-end do aparelho |
| Q21 | DNS erro e IP ping OK | Hipótese de DNS com evidência, sem manobra automática |
| Q22 | Resultado `test failure` no ACS | Falha discriminada e UI sem dados anteriores como novos |

## Níveis de aceite
1. **CI / fake GenieACS:** executar toda matriz Q01–Q22 que possa ser simulada, sem acesso à rede.
2. **Laboratório físico:** uma ONT roteada Device:2 e uma IGD se disponível, outra bridge; testar leitura real com consentimento, sem dados pessoais.
3. **Canário:** ativar por tenant+modelo/firmware permitido, com supervisão NOC, logs e controle de carga.
4. **Produção:** somente com aprovação explícita e documentação/capturas reais; comunicar limitações.

## Evidências exigidas para fechar PR
- Diff + arquivos realmente modificados; testes com comandos e saídas; matriz capability por perfil.
- Registro de uma sequência CWMP (dados saneados) mostrando dispatch, completion e timestamp posterior ao pedido.
- Comprovação de reutilização do SD-001 (service/`speedRunId`, sem segundo adapter).
- Screenshot real de RÁPIDO, COMPLETO parcial, bridge e erro, na Central de Ajuda.
- Link changelog e forma de rollback via flag.
