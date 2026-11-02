# Driver OLT, mapeamento e Profiles

## Limites dos protocolos
- OLT: CLI/SSH, NETCONF/YANG, ou APIs de fabricante comprovadas; SNMP prioritariamente leitura. O protocolo será escolhido pelo driver **homologado**.
- ONU: o estado de descoberta vem da OLT. Não confundir com dispositivo CPE descoberto pelo GenieACS.
- ACS/USP: usado **após ativação PON**, quando suportado; não substitui provisionamento óptico.

## Pipeline do perfil lógico
`template(version)` → `ServiceIntent canonical` → validar com `OLT capability` e `ONU observed capability` → `compile vendor plan` → `discover existing profiles` → `reuse/create proposed` → `render safe diff` → approval → `apply typed actions` → postcheck.

## Huawei GPON — conceitos a mapear por firmware
- DBA profile: agendamento upstream; T-CONT aponta para DBA.
- Line profile: T-CONT, GEM ports e mapeamentos de serviço/VLAN/traffic.
- Service profile: capacidades físicas e serviço ONU (portas GE/POTS/Wi-Fi quando aplicável), modelo e capacidade.
- ONT registration: serial/LOID/password conforme modo suportado, ONU-ID disponível e PON correta, vincular line/service profile.
- Service-port, VLAN, uplink/tráfego: validar separadamente e confirmar o forwarding; planos de banda podem ser aplicados no BNG/OLT/CPE conforme desenho — evitar dupla limitação.
- Perfil já em uso NÃO deve ser sobrescrito; estratégia `new version → new binding → migration approved`, sem alterar clientes antigos inadvertidamente.
- Huawei distributed-mode/profile-mode podem diferir; verificar release e capabilities antes de compilar.

## Catálogo de campos canônicos
`technology` (GPON/EPON/XGS-PON), `service_kind` (internet/voip/iptv/data), `delivery_mode` (bridge/routed), `subscriber_auth` (pppoe/ipoe/none), `customer_vlan` / `service_vlan`, `tagging` / `translation`, `ethernet_port_bindings`, `upstream_assurance_kbps`, `upstream_max_kbps`, `downstream_max_kbps`, `shaping_owner` (bng/olt/cpe/none), `optical_onu_model` / ports, `mgmt_cpe_protocol`, `options` avançadas.

## Exemplos de decisões
- Intent `bridge+PPPoE`: OLT faz VLAN/GEM/port mapping, PPPoE terminado no BNG; ONT não recebe credencial PPPoE por inferência.
- Intent `routed PPPoE ONT`: só oferecer quando equipamento e canal CPE admitirem criação WAN; execução pode exigir dependência de ONT Configuration Manager e testes adicionais.
- Modelo ONU desconhecido pré-autorização: exigir confirmação por técnico/OS ou modo restrito e validação posterior; não fingir descoberta de portas.
- Profile existe com mesmo nome mas hash diferente: `CONFLICT`, sem overwrite.
- Mesmo template em OLTs diferentes: IDs dos perfis locais podem ser distintos; usar mapa lógico→físico por OLT e fingerprint.

## Drivers / homologação
Huawei MA5608T V800R015 (primeiro piloto se disponível); Huawei MA5800 posterior; ZTE, FiberHome, Nokia/Datacom seguintes por demanda. Driver não homologado = READ_ONLY. Não colar exemplos CLI de modelos distintos sem ensaio real de lab.
