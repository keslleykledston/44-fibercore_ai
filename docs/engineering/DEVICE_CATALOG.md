# Catálogo brasileiro FTTx e fábrica de drivers

## O que significa template

Distinguir três artefatos, não confundir:

1. **Identification Profile:** marca/família/modelos, pistas de descoberta, transports esperados, campos suportados e documentação; seed não executável.
2. **Telemetry Adapter Profile:** parsers/OIDs/CLI mapeados por versão, mocks/fFixtures e testes de leitura reproduzíveis; só após evidência.
3. **Action/Provisioning Template:** ações, parâmetros, renderização/dry-run, pré-check, rollback possível, verificação, assinatura, versão; **bloqueado até homologação por firmware/modelo**.

A tabela abaixo orienta filas de investigação. Disponibilidade no mercado não implica suporte ao FiberCore nem CLI universal.

## Famílias OLT consideradas (seed)

| Fabricante | Famílias e exemplos | Fase | Critério de homologação |
|---|---|---|---|
| Huawei | MA5608T, MA5680T, MA5800-X2/X7/X15/X17, EA5800 | R1 | modelo/VRP exatos, `display` parsers e SNMP |
| ZTE | ZXA10 C300, C320, C600/C610/C650 | R1 | firmware exato, CLI/descrição inventário |
| FiberHome | AN5516-01/-04/-06, AN6000 | R2 | variações AN-series, sistema NMS/CLI |
| Datacom | DM4610/11/12/15/16/18 | R2 | DmOS/versão/método documentado |
| Nokia/Alcatel | 7360 ISAM FX, Lightspan famílias | R2 | documentação autenticada e fixture |
| V-SOL | V1600G1/G2, V1600D4 | R2 | distinção GPON/EPON e geração |
| C-DATA | FD1604S/FD1608S/FD1616S | R2 | OIDs/perfis conforme firmware |
| TP-Link | P1200/P1201 e DS-P7001 series | R3 | suporte efetivo e compatibilidade |
| Cianet | G8PSX | R3 | acesso homologado pelo fornecedor |

## CPE/ONU/ONTs (seed por identidade e padrões)

Famílias a catalogar e identificar com OUI/serial/Modelo/Manufacturer/firmware real, **sem prometer capacidades**:

- Huawei EchoLife / OptiXstar (HG/HN/EG/HS conforme datasheets, não presumir que todas têm TR-369);
- ZTE ZXHN (F6xx/F66xx e famílias atuais, dependência de operadora/firmware);
- FiberHome AN5506 / HG series;
- Nokia G-010G / G-140W / Beacon e famílias fornecidas ao ISP;
- Intelbras WiFiber / linhas ONU e roteadores com suporte CWMP a verificar;
- TP-Link XN/XX GPON e roteadores Archer/Aginet sob homologação;
- V-SOL V280x e ONUs GPON/XPON;
- C-DATA ONU/ONT GPON/XPON;
- Datacom DM ONT/ONU;
- outras famílias via community/catalog review (sem permitir plugin executável de tenant).

**Não** garantir controle de Wi-Fi, senha, PPPoE, NAT, VOIP ou upgrade a partir do nome da família. Capacidades resultam de introspecção TR-098/TR-181/USP, firmware, provision, docs ou ensaio.

## Perfis de serviços (modelos de aplicação)

- Internet bridge `service.internet.bridge.v1`
- Internet routed PPPoE `service.internet.pppoe.v1`
- Internet routed DHCP/IPoE `service.internet.ipoe.v1`
- Dual-stack IPv4/IPv6 `service.internet.dualstack.v1`
- Internet + VoIP `service.bundle.voip.v1`
- Internet + IPTV multicast `service.bundle.iptv.v1`
- Internet + CATV `service.bundle.catv.v1`
- Corporativo QinQ/VLAN dedicada `service.enterprise.vlan.v1`
- Gestão Wi-Fi (SSID/channel/band/security) `service.wifi.basic.v1`
- Firmware rollout `service.firmware.canary.v1` (R3, desligado piloto)

Os perfis de serviço descrevem intenção (`intent`), validações e efeitos desejados, não comandos de equipamento. Renderização é responsabilidade do adapter homologado. `dry_run` deve mostrar mudanças sem divulgar PSK/segredo.

## Matriz de capabilities

Para cada combinação `(vendor,model,firmware,protocol,capability)`:

- `supported` = yes/no/unknown;
- `confidence` = identified/observed/certified;
- `read_method` / `write_method` / `path_mapping` / `source_link`;
- `fixture_id` / `lab_run_id` / `verified_by` / `verified_at`;
- `risk` / `rollback_supported` / `postcheck`.

Exemplo: `wifi.ssid.read` em TR-069 TR-181 `Device.WiFi.SSID.*.SSID` *somente quando o CPE efetivamente expuser instâncias e permissão*. Alternativa TR-098 `InternetGatewayDevice.LANDevice.*.WLANConfiguration.*.SSID`. Path wildcard requer resolução da instância, nunca substituição arbitrária de `*`.

## Processo de homologação

1. Identificar `vendor+model+firmware`, documentação oficial e ambiente de lab sem dados pessoais.
2. Capturar fixtures **sanitizadas** de SNMP, CLI, `GetParameterNames`, `GetSupportedDM` ou NBI/USP conforme o transporte.
3. Implementar parser typed, normalizador, erro `UNSUPPORTED`, reprodutibilidade.
4. Executar testes `golden fixtures`, hardware-lab read-only, p95, carga/timeout.
5. Provisionamento: revisão em duas etapas, diff exato, pré-check, operação canário de lab, postcheck e rollback/mitigação.
6. Alterar status para `certified` apenas após evidências e aprovação Codex + engenheiro responsável.

**Repositório externo de comandos copiados de fórum não é fonte suficiente para escrita em produção.**
