# Fontes e decisões verificadas (31/10/2026)

## Bases públicas utilizadas
1. [Broadband Forum Device:2 TR-181i2](https://cwmp-data-models.broadband-forum.org/tr-181-2-15-0-cwmp.html) — `Device.IP.Diagnostics.*`, `Device.DNS.Diagnostics.NSLookupDiagnostics`, `Device.Optical.Interface`, `Device.Ethernet.Interface`, `Device.WiFi.*`, `Device.DeviceInfo.ProcessStatus`.
2. [Broadband Forum IGD:1 TR-098](https://cwmp-data-models.broadband-forum.org/tr-098-1-8-0.html) — `InternetGatewayDevice.IPPingDiagnostics`, `InternetGatewayDevice.TraceRouteDiagnostics`, `InternetGatewayDevice.NSLookupDiagnostics`, `InternetGatewayDevice.DownloadDiagnostics/UploadDiagnostics`, WAN/LAN legados.
3. [Broadband Forum TR-143](https://cwmp-data-models.broadband-forum.org/tr-143-1-1-0.html) — diagnóstico de transferência (pertence ao SD-001 anterior).
4. [GenieACS NBI API Reference](https://docs.genieacs.com/en/latest/api-reference.html) — tasks `getParameterValues`, `refreshObject`, `setParameterValues`; códigos HTTP 200/202 referem-se à tarefa, não ao fim do diagnóstico.
5. [Modelo Device:2 com Wi-Fi NeighboringDiagnostic](https://cwmp-data-models.broadband-forum.org/tr-181-2-15-0-cwmp.html) — diagnóstico disponível em versões/perfis compatíveis, não inerente a qualquer CPE.

## Decisões do projeto (não provenientes de normas)
- Dois botões apenas (RÁPIDO/COMPLETO), seção compacta no sidebar direito atual; decisão UX para evitar poluição.
- Reusar SD-001 e Edge Connector; decisão de arquitetura incremental do FiberCore 2.2.
- TTLs sugeridos e limites de ping/DNS são valores operacionais de partida, **não obrigatórios por padrão Broadband Forum**.
- Correlação via regras determinísticas e conclusões probabilísticas, não score SLA.

## Pontos que exigem validação em hardware
- Suporte real a `Device.IP.Diagnostics.*` vs `InternetGatewayDevice.*` por firmware.
- Campos TR-181 ópticos não são garantidos em toda ONT; fallback pela OLT se já existir integração homologada.
- Dado de WAN de gestão nem sempre usa mesma interface/roteamento da internet do cliente.
- Relação entre eventos `8 DIAGNOSTICS COMPLETE` e run novo; timestamps reais de objeto CWMP e capacidade de acompanhar jobs assíncronos.
- Suporte de métodos e cancelamento em firmware antigo: não supor `Canceled` disponível.
