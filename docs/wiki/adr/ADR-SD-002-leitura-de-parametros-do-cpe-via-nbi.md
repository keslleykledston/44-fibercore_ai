# ADR-SD-002: Leitura de parâmetros do CPE (WAN/Wi-Fi) via NBI do GenieACS

Status: Accepted (leitura passiva e leitura ativa autorizadas pelo responsável em 2026-10-29; a ativa vem desligada por configuração) | Data: 2026-10-29 | Owner: equipe | Origem: ADR-0025 item 8, relatório B0 (lacuna "WAN/PPPoE/Wi-Fi")

## Contexto
O diagnóstico de WAN e Wi-Fi (R-D002…R-D004) precisa de estado do CPE. A projeção atual do coletor é deliberadamente `_id,_lastInform,_deviceId`: nenhuma árvore de parâmetros sai do site, para que PSK, usuário PPPoE e SSID nunca cheguem à nuvem. O responsável autorizou a **leitura** do NBI (2026-10-29).

**Evidência na LAB (somente nomes de caminho, sem valores, 2026-10-29):** dos 43 dispositivos no GenieACS, 5 têm árvore de parâmetros (3 TR-098, 2 TR-181) e ela contém só dados do Inform (`DeviceInfo.*`, `ManagementServer.*`). **Nenhum** tem `WANDevice`, `WLANConfiguration`, `Device.WiFi` ou `Device.PPP`. Ler o que o GenieACS já tem em cache, portanto, devolve vazio para WAN/Wi-Fi hoje.

## Decisão
1. **Leitura passiva (implementada, `agents/edge/internal/nbi/params.go`):** `GET /devices` com projeção de **folhas exatas** de uma lista fechada no código (nunca configurável pela nuvem; nunca subárvore, para não arrastar irmãos sensíveis como `KeyPassphrase`). Só entram: status de enlace/conexão WAN, uptime, rádio habilitado e canal, e uptime do dispositivo (TR-098 e TR-181).
2. **Validação por tipo na saída:** cada valor só passa se o caminho está na lista **e** o valor é de tipo/lista esperado (enum fechado, inteiro em faixa, booleano). Texto livre (SSID, usuário, senha, MAC, IP) nunca é lido nem repassado; o que não passa é descartado e contado. Valor sem `_timestamp` válido é descartado (idade desconhecida não serve a diagnóstico). O extrator caminha **apenas** pelos caminhos permitidos; ramos desconhecidos nem são olhados.
3. **Contrato:** as métricas viram evidência no envelope `contracts/sd001/evidence-envelope.schema.json` (nomes de métrica e estados de listas fechadas; teste cruzado Go↔contrato em `test_sd001_contracts.py`).
4. **Leitura ativa (autorizada em 2026-10-29, implementada, DESLIGADA por padrão):** como o cache não tem WAN/Wi-Fi, o Edge pede ao ACS uma tarefa `getParameterValues` por grupo de objetos (`POST /devices/{id}/tasks?connection_request`), uma de cada vez, só com nomes da lista fechada. Limites:
   - **Só por job assinado `refresh`** (R0, `ReadOnlyOps`); a nuvem assina o `target_ref` (id do dispositivo no ACS, do binding TR-069 do CPE) no envelope e o Edge o revalida. O Edge só age com `refresh_tasks: true` (exige `nbi_url` e `jobs_enabled`); sem isso um refresh que nomeia dispositivo falha fechado, nunca vira coleta silenciosa.
   - **Ritmo persistido antes de qualquer requisição:** no máximo 1 por dispositivo a cada 10 min e 20 por hora no total; arquivo de estado ilegível bloqueia por uma hora; falha ao gravar = nenhuma requisição.
   - **Sem lote:** um dispositivo por job; sem varredura por PON.
   - **Detecção do modelo de dados antes de pedir** (TR-098 ou TR-181; ambíguo ou desconhecido = nada é pedido); identidades de descoberta (`DISCOVERYSERVICE`) recusadas.
   - **Limpeza obrigatória:** se uma tarefa que não concluiu não puder ser removida (DELETE falhou ou o ACS não devolveu id válido) o refresh FALHA, nenhuma tarefa nova é criada e o dispositivo fica retido por 24 h no estado local (o log local nomeia o dispositivo para o operador conferir o ACS; a nuvem recebe só a categoria). Tarefa que não concluiu (fila/falha) é removida com `DELETE /tasks/{id}`, apenas de ids devolvidos pelo ACS na própria chamada e com formato validado, para não deixar tarefa em repetição num CPE de cliente.
   - O cliente do Edge só pode: GET de dispositivos, POST de tarefa `getParameterValues` e DELETE de tarefa; um teste varre o código-fonte por qualquer outro nome de tarefa.
   - O resultado vai ao job só como contagens (grupos, concluídos, falhos, métricas legíveis); nenhum valor de parâmetro sai nesta etapa.
5. **Fora de escopo:** estação associada/RSSI por cliente (exige enumerar `AssociatedDevice`, que traz MAC), PPPoE (usuário/IP), qualquer escrita.

## Consequências
Com a leitura ativa ligada, o cache do ACS passa a ter WAN/Wi-Fi dos CPEs consultados e o leitor passivo os lê; **o transporte desses valores para a nuvem (`cpe_state`, migração) é o próximo PR**. Até lá R-D002…R-D004 seguem sem fonte e o produto diz isso (desconhecido), nunca zero. Risco residual: cada refresh dispara uma conexão ao CPE do cliente; por isso o ritmo, o job assinado e o desligado-por-padrão.
