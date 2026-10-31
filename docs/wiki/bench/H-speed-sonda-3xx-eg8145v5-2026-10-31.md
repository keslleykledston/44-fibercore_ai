# Sonda de 3xx do cliente TR-143 — Huawei EG8145V5 (V5R019C10S350) — 2026-10-31

Escopo: SOMENTE a ONT de bancada. Pré-requisito do gate `redirect_unverified` do Speed Diagnostics (ADR-0038 item 4). Sem credencial, endereço ou dado de cliente.

## Resultado
**A ONT SEGUE redirecionamento HTTP 3xx.** Linha do registro: `speed_test_redirect_probe` = **`unsupported`** (`observed`). Consequência: o gate continua em `redirect_unverified` para este modelo/firmware até existir a ACL de saída real (`speed_test_egress_acl supported`, confirmada pela rede) ou emenda formal do ADR-0038 aceita pelo responsável. **Nenhum teste de banda foi liberado.**

## Autorização
Responsável, no chat da sessão, 2026-10-31: "opção A Sonda de 3xx - autorizado". Escopo: uma ONT (a de bancada), servidores de sonda temporários do próprio LAB, janela curta.

## Identidade conferida antes da tarefa
ACS: exatamente 1 dispositivo com OUI `00259E`, classe `EG8145V5` e o serial de bancada da lista local (identificado aqui só pelos 4 últimos caracteres, `…7AA5`); nenhuma tarefa pendente; sem falhas.

## Procedimento
1. Dois servidores HTTP temporários no host do LAB, em portas próprias, liberados no firewall só para as faixas de origem do provedor e removidos ao fim: **R** responde `302` a `GET` apontando para **C**; **C** conta visitas e devolve 1 000 bytes.
2. Uma tarefa `setParameterValues` no objeto `InternetGatewayDevice.DownloadDiagnostics` (`Interface` = WAN de serviço da bancada, `DownloadURL` = R, `DiagnosticsState` = `Requested`), o mesmo conjunto que o Edge envia.
3. Tentativa 1, com Connection Request: HTTP 202 (a ONT não atendeu a tempo). A própria tarefa foi **removida** e nada foi executado (0 visitas na sonda). Tentativa 2, **sem** Connection Request: ficou na fila e a ONT a executou no Inform seguinte (~60 s). Uma `getParameterValues` leu os resultados (~360 s). Ao fim: 0 tarefas pendentes na ONT; nenhum outro dispositivo foi tocado.

## Observado
| Item | Valor |
|---|---|
| Visitas em R / em C | 1 / 1 (C atendida 1,1 s depois de R, 2026-10-31 16:58:33–34 UTC) |
| `DiagnosticsState` | `Completed` |
| `TestBytesReceived` / `TotalBytesReceived` / `TotalBytesSent` | 1282 / 1512 / 571 (a resposta de C: 1 000 B de corpo + cabeçalhos) |
| `ROMTime` / `BOMTime` / `EOMTime` | valores brutos no horário do DISPOSITIVO (zona desconhecida, não UTC): `ROMTime` = `2026-10-31T12:52:09.712`, `BOMTime` = `2026-10-31T12:52:09.712`, `EOMTime` = `2026-10-31T12:52:09.726`; BOM→EOM = 14 ms. O relógio da ONT estava desalinhado do UTC da coleta (16:58 UTC) por cerca de 4 h, estimativa sem NTP confirmado; só as diferenças entre os três valores são confiáveis |
| Origem vista pelo nó | endereço público do NAT do provedor (faixa distinta de `100.64.0.0/10`); a lista de origens do nó de teste foi corrigida para esse endereço |

## Fatos para a planilha de homologação (`docs/operations/SPEED_HOMOLOGACAO.md`)
- `DownloadDiagnostics` presente e `DiagnosticsState` gravável (modelo IGD:1, raiz `InternetGatewayDevice`).
- Folhas de resultado presentes: `ROMTime`, `BOMTime`, `EOMTime`, `TestBytesReceived`, `TotalBytesReceived`, `TotalBytesSent`. `UploadDiagnostics`: **não testado**.
- Caminho da WAN de serviço aceito em `Interface`: `InternetGatewayDevice.WANDevice.1.WANConnectionDevice.3.WANPPPConnection.1`.
- A ONT **atende o Connection Request só às vezes**: a tarefa funcionou na fila, no Inform. O Edge trata 202 removendo a própria tarefa e não reenvia, então um teste de banda real pode falhar com "ONT inalcançável" até o Connection Request ser confiável.

## Próximo
Decisão do responsável: (B) ACL de saída real na WAN de serviço da bancada confirmada pela rede, ou (C) emenda do ADR-0038 aceitando o risco residual na bancada. A sonda não precisa ser repetida.
