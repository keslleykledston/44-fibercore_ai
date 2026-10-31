# Catálogo de campos normalizados e possíveis caminhos (NÃO homologados)

## Regras de mapeamento
1. Uma capability é semântica (`wifi.ssid.write`), não um parâmetro fixo do ACS. Resolver instâncias reais para cada modelo antes de mostrar campos editáveis.
2. Nunca assumir `WiFi.Radio.1` é 2.4 GHz, `WiFi.SSID.2` é 5 GHz, nem `WLANConfiguration.1` é WLAN desejada. Descobrir associação por `LowerLayers`, interface/SSID/AccessPoint e banda efetiva.
3. Paths nesta tabela são **candidatos documentais**, sujeitos a introspecção TR-098, TR-181, USP `GetSupportedDM`, políticas dos fabricantes e observação de firmware. Nunca usá-los para write diretamente sem matriz certificada.
4. Faixas, enums e valores aceitos devem vir de schema oficial, dispositivo ou laboratório. Não converter slider arbitrário 0–100% em dBm, mW ou enum proprietário.
5. Segredo não é observação: senhas PPPoE/Wi-Fi nunca aparecem em GET, diff, screenshot, logs ou tickets. Usar `secret_ref` com TTL e no echo.

| Campo canônico | Caminho candidato TR-181 (CWMP/USP) | TR-098 candidato | Operação |
|---|---|---|---|
| `wifi.ssid` | `Device.WiFi.SSID.{i}.SSID` | `InternetGatewayDevice.LANDevice.{i}.WLANConfiguration.{i}.SSID` | read/write condicional |
| `wifi.enabled` | `Device.WiFi.Radio.{i}.Enable` ou `Device.WiFi.AccessPoint.{i}.Enable` (não equivalentes) | `InternetGatewayDevice.LANDevice.{i}.WLANConfiguration.{i}.Enable` | read/write condicional |
| `wifi.channel` | `Device.WiFi.Radio.{i}.Channel` | `InternetGatewayDevice.LANDevice.{i}.WLANConfiguration.{i}.Channel` | read/write condicional |
| `wifi.channel_auto` | `Device.WiFi.Radio.{i}.AutoChannelEnable` | suporte via modelo | read/write condicional |
| `wifi.channel_width` | `Device.WiFi.Radio.{i}.OperatingChannelBandwidth` | verificar firmware | read/write condicional |
| `wifi.transmit_power` | `Device.WiFi.Radio.{i}.TransmitPower` (validar definição/faixa) | variantes vendor-specific | read/write somente homologado |
| `wifi.security_mode` | `Device.WiFi.AccessPoint.{i}.Security.ModeEnabled` | `WLANConfiguration.{i}.BeaconType` e relacionados | read/write condicional |
| `wifi.password` | `Device.WiFi.AccessPoint.{i}.Security.KeyPassphrase` ou variantes (verificar) | `WLANConfiguration.{i}.PreSharedKey.{i}.PreSharedKey` ou variantes | WRITE ONLY no FiberCore |
| `lan.ipv4_address` | `Device.IP.Interface.{i}.IPv4Address.{i}.IPAddress` | `InternetGatewayDevice.LANDevice.{i}.LANHostConfigManagement.IPInterface.{i}.IPInterfaceIPAddress` | P1 alto risco |
| `lan.netmask` | `Device.IP.Interface.{i}.IPv4Address.{i}.SubnetMask` | `...IPInterfaceSubnetMask` | P1 alto risco |
| `lan.dhcp_pool` | `Device.DHCPv4.Server.Pool.{i}.MinAddress/MaxAddress` | `...LANHostConfigManagement.MinAddress/MaxAddress` | P1 alto risco |
| `lan.dhcp_enabled` | `Device.DHCPv4.Server.Pool.{i}.Enable` | `...LANHostConfigManagement.DHCPServerEnable` | P1 alto risco |
| `lan.dns` | `Device.DHCPv4.Server.Pool.{i}.DNSServers` | `...LANHostConfigManagement.DNSServers` | P1 alto risco |
| `wan.pppoe` | dependente da árvore PPP + lower layers/interface | `WANPPPConnection.{i}.*` | P2 crítico |
| `wan.vlan` | `Device.Ethernet.VLANTermination.{i}.*` ou bridge conforme dados reais | vendor-specific WAN | P2 crítico |
| `wan.ipv6` | `Device.IP.Interface.{i}.IPv6*` / DHCPv6 / RA | vendor-specific | P2 crítico |
| `optical.rx_dbm` | Vendor optic path se disponível | Vendor optic path se disponível | read-only |
| `optical.tx_dbm` | Vendor optic path se disponível | Vendor optic path se disponível | read-only |

**Observação de rádio:** o RFC/modelo de dados pode apresentar diferentes percentuais e suportes para `TransmitPower`; a configuração real pode estar em `%`, `dBm`, enum ou ser inacessível — tratar como `raw_unit` até validação do dispositivo. Valores ópticos são medições de transceptor, não potência Wi-Fi.

## Descoberta por protocolo
- **TR-069 / GenieACS:** GET NBI `devices` com projeção restrita e `query`; quando necessário, `refreshObject`/`getParameterValues` através do mecanismo de tarefas e informe do CPE. Escrita pela NBI `setParameterValues` apenas após aprovação/adapter certificado. Não assumir que o `getParameterValues` entrega instante em tempo real: aguardar a sessão e checar timestamps.
- **TR-369 / USP:** o Controller resolve `GetSupportedDM` e `Get`; `Set`/`Operate` pelo controlador homologado; verificar instâncias e ACLs do USP Agent. Não confundir controller com GenieACS.
- **OLT:** leituras OMCI/CLI/SNMP para PON/óptica são outra fonte, sem converter comandos OLT em alteração de potência óptica.

## Identity & adapter profile
Guarde `vendor`, `oui`, `product_class`, `model`, `hw_revision`, `firmware_version`, `protocol`, `controller_connection_id`, `external_device_id`, `matched_rule`, `status`, `certified_at`, `evidence_hash`, `raw_parameter_binding`. Presets e mappings têm rollback por versionamento de perfil, não garantia de reversão de mudança no dispositivo.
