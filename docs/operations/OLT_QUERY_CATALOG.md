# Catálogo de consultas da OLT (MA5608T / MA5600V800R015)

Fonte: runbook operacional de diagnóstico somente leitura (referência). Implementação: `agents/edge/internal/olt/query.go` (ADR-0026). **Nada disto é executado hoje por nenhum fluxo**; é a base para as tools.

Legenda: **V** = já executado na OLT real e coberto por fixture (aceito por padrão). **N** = sintaxe do runbook, ainda não executada nesta release (recusada até habilitação local para captura supervisionada).

| ID | Comando | Escopo | Estado | Runbook |
|---|---|---|---|---|
| `olt.version` | `display version` | global | V | 3 |
| `olt.board` | `display board 0` | global | V | 3 |
| `olt.time` | `display time` | global | V | 2 |
| `olt.alarm.active` | `display alarm active all` | global | N | 2 |
| `olt.alarm.history` | `display alarm history all list` | global | N | 2 |
| `olt.event.history` | `display event history all list` | global | N | 3 |
| `olt.autofind` | `display ont autofind all` | global | N | 2 |
| `olt.temperature` | `display temperature 0` | global | V | 3 |
| `olt.sync` | `display data sync state` | global | V | 3 |
| `slot.board` | `display board 0/<slot>` | slot | N | 3 |
| `slot.cpu` | `display cpu 0/<slot>` | slot | S (validada em 31/10/2026; ainda não oferecida: falta o seletor de slot na tela) | 3 |
| `slot.mem` | `display mem 0/<slot>` | slot | S (validada em 31/10/2026; ainda não oferecida: falta o seletor de slot na tela) | 3 |
| `pon.ont.info` | `display ont info <porta> all` | PON | V | 5 |
| `pon.ont.optical` | `display ont optical-info <porta> all` | PON | V | 6 |
| `pon.ont.summary` | `display ont info summary <porta>` | PON | N | 5 |
| `pon.port.info` | `display port info <porta>` | PON | N | 6 |
| `pon.port.state` | `display port state <porta>` | PON | N | 6 |
| `pon.ont.autofind` | `display ont autofind <porta>` | PON | N | 5 |
| `onu.info` | `display ont info <porta> <ont>` | ONU | N | 7 |
| `onu.optical` | `display ont optical-info <porta> <ont>` | ONU | N | 8 |
| `onu.register` | `display ont register-info <porta> <ont>` | ONU | N | 9 |
| `onu.alarm` | `display ont alarm-state <porta> <ont>` | ONU | N | 7 |
| `onu.version` | `display ont version <porta> <ont>` | ONU | N | 7 |
| `onu.capability` | `display ont capability <porta> <ont>` | ONU | N | 7 |
| `onu.eth` | `display ont port state <porta> <ont> eth-port all` | ONU | N | 10 |

Consultas PON/ONU rodam dentro de `interface gpon 0/<slot>`.

## Ainda fora do catálogo (precisam de decisão ou de mais cuidado)
- Uplink/serviço/MAC (`interface mcu`, `display port state all`, `display vlan all`, `display service-port …`, `display mac-address vlan …`): dependem da placa de controle (mcu×scu) e mudam de contexto; saída grande.
- Tráfego e estatísticas (`display ont traffic …`, `display statistics ont-eth …`): variam por placa/ONU.
- Qualquer coisa com `undo`, `reset`, `save`, `ont add/delete`, ativação, perfis: **escrita**, bloqueada (`HOMOLOGATED_WRITES` vazio).

## Captura supervisionada de uma consulta N (para promovê-la)
1. Um responsável habilita só aquele ID no Edge, em janela combinada, respeitando o ritmo do guard (uma consulta por vez, sem concorrer com a coleta periódica).
2. A saída crua fica **só no Edge**, com permissão 0600; não vai à nuvem, ao repositório, à Lovable nem ao ai-memory.
3. Sanitizar (serial, descrição, nome de host, IP, horário, qualquer texto de cliente) e salvar como fixture em `agents/edge/internal/olt/testdata/`.
4. Escrever parser + teste com a fixture; só então mudar o flag do ID para validado, no mesmo PR, com revisão do Codex.
