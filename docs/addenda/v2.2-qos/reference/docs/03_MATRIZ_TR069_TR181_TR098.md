# Matriz de capacidades — TR-069 CWMP com Device:2 e IGD:1

**Leia antes:** TR-069 é transporte/protocolo de gerenciamento, não garantia de parâmetros. TR-181 (Device:2) e TR-098 (InternetGatewayDevice:1) variam com perfil/versão; cada ONT deve ser descoberta e homologada. Caminhos com `{i}` são instâncias descobertas, NUNCA valores fixos.

## Diagnósticos ativos (somente após verificar parâmetro/firmware/writable)
| Teste | Device:2 (TR-181) | IGD:1 (TR-098) | Resultado e observações |
|---|---|---|---|
| Ping | `Device.IP.Diagnostics.IPPing.` | `InternetGatewayDevice.IPPingDiagnostics.` | `SuccessCount`, `FailureCount`, RTT min/média/máx (ms); perda = falhas / (sucessos+falhas) quando execução íntegra; sem jitter intrínseco |
| DNS | `Device.DNS.Diagnostics.NSLookupDiagnostics.` | `InternetGatewayDevice.NSLookupDiagnostics.` **se presente** | `SuccessCount`, `Result.{i}.Status`, `ResponseTime`; disponibilidade por perfil/versão |
| Traceroute | `Device.IP.Diagnostics.TraceRoute.` | `InternetGatewayDevice.TraceRouteDiagnostics.` | Saltos e tempos se fornecidos; ICMP bloqueado não é automaticamente falha da internet |
| Download TR-143 | `Device.IP.Diagnostics.DownloadDiagnostics.` | `InternetGatewayDevice.DownloadDiagnostics.` | **SD-001 existente**; não reimplementar |
| Upload TR-143 | `Device.IP.Diagnostics.UploadDiagnostics.` | `InternetGatewayDevice.UploadDiagnostics.` | **SD-001 existente**; não reimplementar |
| UDP Echo | `Device.IP.Diagnostics.UDPEchoDiagnostics.` | Descobrir perfil/vendor | P1 opcional; NÃO tratar como jitter padrão sem granularidade válida |
| Vizinhos Wi-Fi | `Device.WiFi.NeighboringWiFiDiagnostic.` | Não padronizado da mesma forma em IGD clássico | P1 opcional e pode interferir rádio; não ativar automaticamente |

## Leituras passivas / telemetria
| Campo | TR-181 | TR-098 / alternativo | Cuidados |
|---|---|---|---|
| WAN e IPv4/IPv6 | `Device.IP.Interface.{i}.` | `InternetGatewayDevice.WANDevice.{i}.WANConnectionDevice.{i}.WANIPConnection.{i}.` | Identificar WAN de **serviço**, rota, VLAN e status; distinguir gestão/bridge |
| PPP | `Device.PPP.Interface.{i}.` | `...WANPPPConnection.{i}.` | Estado só se o próprio CPE termina a sessão; bridge não representa PPPoE do roteador do cliente |
| Ethernet | `Device.Ethernet.Interface.{i}.` e `.Stats.` | `InternetGatewayDevice.LANDevice.{i}.LANEthernetInterfaceConfig.{i}.` | Link / 100M/1G/2.5G, errors, drops; contadores acumulados têm de ser diferenciados entre dois instantes |
| Wi-Fi | `Device.WiFi.Radio.{i}.`, `Device.WiFi.SSID.{i}.`, `Device.WiFi.AccessPoint.{i}.AssociatedDevice.{i}.` | `InternetGatewayDevice.LANDevice.{i}.WLANConfiguration.{i}.` e descendentes | RSSI PHY, canal, retransmissão se expostos; PHY ≠ throughput, evita revelar identificadores dos clientes |
| Óptica | `Device.Optical.Interface.{i}.` (se implementado) | `X_...` vendor ou **adapter OLT existente** | RX `OpticalSignalLevel` em dBm×1000; limites por classe óptica/vendor, sem limiar fixo global |
| CPU/memória | `Device.DeviceInfo.ProcessStatus.CPUUsage`, `Device.DeviceInfo.MemoryStatus.` | Vendor ou `Device.DeviceInfo` equivalente se realmente presente | Ponderar CPU sob teste vs idle; sem inferir problema com uma amostra |
| Uptime | `Device.DeviceInfo.UpTime` | `InternetGatewayDevice.DeviceInfo.UpTime` | Reinício ≠ queda PON; correlacionar com eventos quando houver |

## Política de disponibilidade
- `SUPPORTED/HOMOLOGATED`: teste e campos comprovados naquele perfil+firmware+WAN; pode executar sob RBAC.
- `PRESENT_UNVERIFIED`: objeto presente, mas ciclo de execução não validado; somente leitura ou laboratório, ação ativa bloqueada por padrão.
- `PARTIAL`: alguns indicadores disponíveis; resultado parcial é legítimo.
- `UNSUPPORTED`: comprovadamente ausente/negado.
- `UNKNOWN`: não descoberto, ACS sem contato, versão alterada etc.
- Vendor extensions: whitelist por modelo+firmware, com unidade, escala, docs, amostra de leitura e testes; não adivinhar caminhos `X_HW`/`X_ZTE`.

## Validações de unidade e semântica
- `Device.Optical.Interface.{i}.OpticalSignalLevel` reporta dBm × 1000: `-23500` → `-23,5 dBm`. Outros vendors podem usar centésimos, centésimos de dBm ou valores sem unidade: só converter após homologação.
- `Ping` RTT em ms e loss relativo à amostra; ping bem-sucedido não prova throughput.
- PHY Wi-Fi e link Ethernet são taxas de enlace negociadas, não teste de vazão.
- Contadores de bytes/erros: diferenças por tempo e detecção de reset, overflow e reboot; não multiplicar contagens por segundo sem intervalo válido.
- Prefixo IGD na ponta e mapeamento por `SupportedDataModel`; não presumir TR-181 em ONTs antigas.

## Referências oficiais
Broadband Forum TR-181 Device:2: https://cwmp-data-models.broadband-forum.org/tr-181-2-15-0-cwmp.html
Broadband Forum TR-098 IGD:1: https://cwmp-data-models.broadband-forum.org/tr-098-1-8-0.html
Broadband Forum TR-143: https://cwmp-data-models.broadband-forum.org/tr-143-1-1-0.html
GenieACS NBI: https://docs.genieacs.com/en/latest/api-reference.html
