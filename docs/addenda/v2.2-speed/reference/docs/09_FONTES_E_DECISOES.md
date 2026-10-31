# Referências e esclarecimentos técnicos

## Oficiais
1. TR-143 XML modelo CWMP: https://cwmp-data-models.broadband-forum.org/tr-143-1-0-1.html
2. TR-143 Amendment 1: https://cwmp-data-models.broadband-forum.org/tr-143-1-1-0.html
3. Procedimentos de teste Broadband Forum (GET, upload HTTP, Inform etc.): https://cwmp-data-model-test.broadband-forum.org/06-index-test-procedures.html
4. GenieACS API NBI: https://docs.genieacs.com/en/latest/api-reference.html

## Correções de interpretação
- NBI HTTP 200 confirma **execução de tarefa**, não speedtest concluído.
- NBI HTTP 202 confirma **enfileiramento**, não erro nem conclusão.
- Evento CWMP `8 DIAGNOSTICS COMPLETE` é gerado pelo CPE ao concluir diagnóstico quando implementado; a exposição desse evento ao FiberCore depende da integração atual. **Não inventar webhook nativo do NBI.**
- Upload HTTP TR-143 usa **PUT**. Um Test Node que atende só POST não resolve o teste legado.
- Para download, throughput de transação usa `TestBytesReceived`; para upload legado concluído, `TestFileLength`, e não `TotalBytesSent` se este contar também outros tráfegos.
- Resultados de uplink podem ser inflados se `TotalBytesSent` do enlace incluir tráfego concorrente: separar taxa da transação e total da interface.
- `Device.IP.Diagnostics` e `InternetGatewayDevice` variam; Device root não implica performance disponível.
- Diferenciar rota pela WAN de serviço da VLAN de gerenciamento e não confundir teste da ONT com teste no Wi-Fi do cliente.
- TR-369 e TR-471 não são objetivos deste incremento; controller USP segue arquitetura atual.
