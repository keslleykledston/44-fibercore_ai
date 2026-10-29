# ADR-SD-002: Leitura de parâmetros do CPE (WAN/Wi-Fi) via NBI do GenieACS

Status: Proposed (a parte passiva está implementada; a parte ativa aguarda autorização explícita) | Data: 2026-10-29 | Owner: equipe | Origem: ADR-0025 item 8, relatório B0 (lacuna "WAN/PPPoE/Wi-Fi")

## Contexto
O diagnóstico de WAN e Wi-Fi (R-D002…R-D004) precisa de estado do CPE. A projeção atual do coletor é deliberadamente `_id,_lastInform,_deviceId`: nenhuma árvore de parâmetros sai do site, para que PSK, usuário PPPoE e SSID nunca cheguem à nuvem. O responsável autorizou a **leitura** do NBI (2026-10-29).

**Evidência na LAB (somente nomes de caminho, sem valores, 2026-10-29):** dos 43 dispositivos no GenieACS, 5 têm árvore de parâmetros (3 TR-098, 2 TR-181) e ela contém só dados do Inform (`DeviceInfo.*`, `ManagementServer.*`). **Nenhum** tem `WANDevice`, `WLANConfiguration`, `Device.WiFi` ou `Device.PPP`. Ler o que o GenieACS já tem em cache, portanto, devolve vazio para WAN/Wi-Fi hoje.

## Decisão
1. **Leitura passiva (implementada, `agents/edge/internal/nbi/params.go`):** `GET /devices` com projeção de **folhas exatas** de uma lista fechada no código (nunca configurável pela nuvem; nunca subárvore, para não arrastar irmãos sensíveis como `KeyPassphrase`). Só entram: status de enlace/conexão WAN, uptime, rádio habilitado e canal, e uptime do dispositivo (TR-098 e TR-181).
2. **Validação por tipo na saída:** cada valor só passa se o caminho está na lista **e** o valor é de tipo/lista esperado (enum fechado, inteiro em faixa, booleano). Texto livre (SSID, usuário, senha, MAC, IP) nunca é lido nem repassado; o que não passa é descartado e contado. Valor sem `_timestamp` válido é descartado (idade desconhecida não serve a diagnóstico). O extrator caminha **apenas** pelos caminhos permitidos; ramos desconhecidos nem são olhados.
3. **Contrato:** as métricas viram evidência no envelope `contracts/sd001/evidence-envelope.schema.json` (nomes de métrica e estados de listas fechadas; teste cruzado Go↔contrato em `test_sd001_contracts.py`).
4. **Leitura ativa (NÃO autorizada por este ADR):** como o cache não tem WAN/Wi-Fi, obtê-los exige que o ACS peça ao CPE (`getParameterValues` via `POST /devices/{id}/tasks`). Isso enfileira tarefa no ACS e dispara conexão com o CPE do cliente; o cliente NBI do Edge é só-GET por construção. Só será implementada se o responsável autorizar **explicitamente** esse tipo de tarefa, com: apenas `getParameterValues`, apenas os caminhos da lista, uma tarefa por dispositivo por janela mínima, execução somente por job assinado `refresh` (R0, já em `ReadOnlyOps`), nunca em lote por PON, e kill switch.
5. **Fora de escopo:** estação associada/RSSI por cliente (exige enumerar `AssociatedDevice`, que traz MAC), PPPoE (usuário/IP), qualquer escrita.

## Consequências
Nada novo é enviado à nuvem neste PR (o coletor não usa o leitor; não há endpoint nem migração). O próximo passo de dados depende da decisão do item 4. Sem ela, R-D002…R-D004 continuam sem fonte e o produto diz isso (não suportado/desconhecido), nunca zero.
