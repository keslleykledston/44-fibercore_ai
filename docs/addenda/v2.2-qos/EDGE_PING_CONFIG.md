# Edge — teste de ping (IPPing, TR-143) na bancada

Operação `ping_test` (ADR-0030, emenda de 2026-10-31, linha Q1; ADR-0039). Só para os CPEs da lista fechada de bancada, TR-069, pelo mesmo caminho de toda escrita de bancada (autorização prévia de uso único, claim durável, lease, identidade conferida no ACS, no máximo uma tarefa por teste, nunca reenviada).

## Configuração local (arquivo 0600, nunca na nuvem)
```json
"allowed_operations": ["…", "ping_test"],
"bench": { "bench_writes_enabled": true, "devices": [ { "oui": "…", "product_class": "…", "serial": "…",
           "speed_wan_interface": "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.<n>.WANPPPConnection.<m>" } ] },
"ping": { "enabled": true, "core_cidrs": ["10.20.0.0/16"],
          "targets": [ {"id": "core-lab", "kind": "CORE", "host": "10.20.5.9"},
                       {"id": "dns-publico", "kind": "INTERNET", "host": "9.9.9.9"} ] }
```
- `targets[].id` é o nome LÓGICO que a nuvem conhece; o endereço só existe aqui. `host` é um IP literal (nada a resolver). Regras idênticas às do teste de banda: nunca loopback, link-local (inclui metadados de nuvem), multicast ou reservado; `INTERNET` nunca privado, CGNAT ou de documentação; `CORE` dentro de `core_cidrs`.
- O Edge fixa a forma do teste: **5 repetições e timeout de 1000 ms**. A nuvem não escolhe nem altera.
- **A WAN é a de serviço, por padrão e sempre:** o `Interface` do IPPing é o `speed_wan_interface` do aparelho (o mesmo do teste de banda). Antes da única escrita o Edge lê o estado dessa WAN e recusa com `wan_not_connected` se não estiver conectada, ausente ou ilegível. O ping mede o caminho que o provedor entrega ao cliente.
- Nenhuma entrada em `allowlist` é necessária: o ICMP sai do CPE, não do Edge.

## O que o aparelho precisa expor
`IPPingDiagnostics` (TR-098: `InternetGatewayDevice.IPPingDiagnostics`; TR-181: `Device.IP.Diagnostics.IPPing`) com `DiagnosticsState` gravável e as folhas `SuccessCount`, `FailureCount`, `AverageResponseTime`, `MinimumResponseTime` e `MaximumResponseTime`. Sem elas o teste é recusado ANTES de escrever (`unsupported`).

## O que o relatório contém (formato fechado)
`target` (id lógico), `state` e, quando o aparelho informa, `success`, `failure`, `avg_ms`, `min_ms`, `max_ms` e `polling_ms`. Folha não informada fica de fora, nunca preenchida.

## Limites conhecidos (medidos nos dois aparelhos de bancada, 2026-11-01)
- **Sem jitter.** Esses modelos entregam só mínimo, média e máximo. A diferença máximo − mínimo é a **amplitude**, e não o jitter; latência por pacote não existe nesse objeto.
- **Sem DNS por NSLookup.** Nem a Huawei EG8145V5 nem a ZTE F670L expõem `NSLookupDiagnostics` (nenhuma folha). A latência ao servidor DNS (ping a um destino que seja o resolvedor) mede alcance e latência até ele, não a resolução de nomes.

## Passos do dono na nuvem (depois do Edge)
1. Migração 0038 aplicada (`migrate`).
2. `probe-target-set <tenant> <id> "<rótulo>" CORE|INTERNET <região> on --edge <edge_id>` para cada destino que o Edge lista em `ping.targets` (mesmo id; o endereço fica só no Edge).
3. `capability-set ... ping_test supported identified --evidence ... --verified-at ...` por modelo/firmware (evidência da leitura de `IPPingDiagnostics`); a promoção a `observed` só depois de uma execução real aceita pelo responsável.
4. `bench-authorize <tenant> ping_test <cpe_id> --from ... --to ... --by ... --ping-target <id> [--first-run]` (uso único; os parâmetros são o hash exato do destino).
5. Flags `bench_writes` e `quality_active_tests` ligadas só pela janela do teste.
O pedido pela tela exige `diagnostics:ping_run` e `jobs:request`, e outra pessoa (ou a mesma, como em toda manobra de bancada) aprova; quem autorizou pela API não pode ser quem pede nem quem aprova.
