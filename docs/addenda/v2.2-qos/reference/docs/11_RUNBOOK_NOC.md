# Runbook NOC/N1/N2 — operação do Diagnóstico de Qualidade

## Antes de iniciar
- Conferir ONT selecionada, cliente/tenant e data da última coleta; confirmar permissionamento.
- Em RÁPIDO, verificar que os indicadores não estejam expirados e se a WAN de serviço está identificada.
- Em COMPLETO, obter consentimento/autorização operacional de teste que gera carga na rede; evitar janela de congestionamento ou testes simultâneos na mesma PON.

## Fluxo N1 (RÁPIDO)
1. Abrir ONU 360 > Qualidade > RÁPIDO.
2. Inspecionar sinal (com origem), status WAN/PPPoE, link LAN, Wi-Fi e eventos disponíveis.
3. Executar RÁPIDO (ping Core + DNS se suportados); se parcial, usar somente evidências confiáveis.
4. Se suspeita de Wi-Fi, perguntar se problema ocorre também no cabo; medidas de WAN da ONT não provam performance do telefone/notebook.
5. Encaminhar a N2 com ID do run e evidências; não executar reboot ou mudar Wi-Fi sem aprovação separada.

## Fluxo N2 (COMPLETO)
1. Verificar se modelo/firmware e WAN de serviço estão homologados. Se ONT bridge/gestão-only, usar sonda/roteador do cliente ou procedimento alternativo, sem mascarar origem.
2. Selecionar Core e/ou Internet conforme sintoma; confirmar impacto. Rodar COMPLETO com locks e tempos do SD-001.
3. Comparar somente medições equivalentes, com endpoint saudável e horários próximos. Não concluir falha de trânsito com um único servidor externo.
4. Salvar `qualityRunId` e `speedRunIds`. Se falha do endpoint, não atribuir automaticamente à ONT.
5. Registar hipótese, próximo teste e necessidade de visita/OLT quando faltar evidência.

## Guias de interpretação rápida
| Situação | Procedimento recomendado |
|---|---|
| Sinal óptico abaixo do limite homologado | Validar alarmes e RX/TX da OLT, conectorização e atenuação; não usar limiar universal |
| Porta LAN 100M e plano maior | Verificar negociação, cabo e placa LAN; não confundir com vazão da WAN ONT |
| Ping Core alto ou com perda | Verificar BNG/core, estado PON, carga/filas e resultados de outros destinos |
| DNS lento, ping IP bom | Comparar resolutores cadastrados e erros de lookup |
| Banda Core boa, Internet ruim | Conferir saúde do test node externo, trânsito/rota/peering e horário |
| Wi-Fi baixo, WAN boa | Verificar potência/PHY/retries, cobertura, canal e fazer teste cabo no dispositivo |
| CPE reiniciando, contadores resetando | Correlacionar uptime, energia, firmware, eventos e monitoramento |
| Dados sem suporte ou antigos | Registrar limitação e usar outra medição homologada; não fechar incidente como resolvido |

## Modelo de registro no ticket
`ONT ID: ... | Tenant: ... | Quality Run: ... | Speed Run(s): ... | Tipo: RÁPIDO/COMPLETO | WAN: SERVICE/MGMT/UNVERIFIED | Fonte óptica: TR-069/OLT | Hora UTC: ... | Métricas válidas: ... | Indisponíveis/expiradas: ... | Hipóteses: ... | Próximo teste: ... | Manobra: nenhuma / aprovada em ticket ...`

## Limitações para comunicação com cliente
- "Teste realizado a partir da ONT" ≠ velocidade efetiva no smartphone.
- Resultado pode variar por condição de servidor de teste, latência, simultaneidade e CPU.
- Medida da VLAN ACS/gerência não representa automaticamente a VLAN de internet do cliente.
- Não classificar "SLA cumprido/violado" a partir deste módulo sem metodologia contratual e fonte adicional.
