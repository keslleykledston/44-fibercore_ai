# Sonda de 3xx do cliente TR-143 — ZTE F670L (V9.0.11P1N10B) — 2026-11-01

Escopo: SOMENTE a ONT de bancada ZTE F670L. Pré-requisito do gate `redirect_unverified` do Speed Diagnostics (ADR-0038 item 4). Sem credencial, endereço ou dado de cliente.

## Resultado
**A ZTE SEGUE redirecionamento HTTP 3xx.** Linha do registro: `speed_test_redirect_probe` = **`unsupported`** (`observed`). Consequência: o gate continua em `redirect_unverified` para este modelo e firmware até existir a ACL de saída real (`speed_test_egress_acl`) ou um aceite vigente do risco (ADR-0038, emenda, opção C).

## Autorização
Responsável, no chat da sessão, 2026-11-01: aceitou a WAN de serviço da ZTE ("1. autorizo"), autorizou a sonda ("2. autorizo"), o aceite do risco de 3xx ("3. autorizo") e a descoberta da origem do tráfego ("4. prossiga"). Escopo: uma ONT (a de bancada), servidores de sonda temporários do próprio LAB, janela curta.

## Identidade conferida antes de cada tarefa
ACS: exatamente 1 dispositivo com OUI `FC4009`, classe `F670L` e serial `ZTE3BJNP5359122`; nenhuma tarefa pendente.

## Procedimento
1. Dois servidores HTTP temporários no host do LAB, em portas próprias: **R** responde `302` a `GET` apontando para **C**; **C** conta visitas e devolve 1 000 bytes. Firewall (`ufw`) aberto só para as origens listadas, com regra temporária, e removido ao fim (conferido: zero regras restantes; servidores encerrados).
2. Uma tarefa `setParameterValues` no objeto `InternetGatewayDevice.DownloadDiagnostics` (`Interface` = a única WAN da ZTE, `DownloadURL` = R, `DiagnosticsState` = `Requested`), com Connection Request (HTTP 200 nas duas tarefas), seguida de `getParameterValues` das folhas de resultado. Uma tarefa por tentativa, sem reenvio.
3. Tentativa 1: `DiagnosticsState = Error_InitConnectionFailed`, 0 visitas em R; a causa desta tentativa é INDETERMINADA (não havia captura). Tentativa 2, mesmo erro, agora com captura de SYN no host (`tcpdump`, só o cabeçalho de SYN para as portas da sonda): 3 SYN da ZTE chegaram ao host, vindos de um endereço público que NÃO estava na lista de origens permitidas do nó nem nas regras da sonda; o firewall os descartou. Para a tentativa 2, a falha é explicada pela origem não liberada, e a tentativa 3 (sucesso depois de liberá-la) sustenta isso. Não afirmo a mesma causa para a tentativa 1.
4. Tentativa 3, com essa origem incluída SÓ nas regras temporárias da sonda: resultado abaixo. A lista de origens do nó de teste não foi alterada por esta sonda.

## Observado (tentativa 3)
| Item | Valor |
|---|---|
| Visitas em R / em C | 1 / 1 (C atendida ~25 ms depois de R) |
| `DiagnosticsState` | `Completed` |
| `TestBytesReceived` / `TotalBytesReceived` / `TotalBytesSent` | 1000 / 0 / 0 (a ZTE conta só o corpo de C em `TestBytesReceived`; não preenche os totais) |
| `ROMTime` / `BOMTime` / `EOMTime` | valores brutos no horário do DISPOSITIVO, com data de 1970 (relógio sem sincronismo): `ROMTime` = `1970-01-01T00:49:22.736`, `BOMTime` = `…22.772`, `EOMTime` = `…22.774`; BOM→EOM = 2 ms; não são UTC e não se comparam com o relógio da nuvem |
| Origem vista pelo host | endereço público, fora de `100.64.0.0/10` e não privado; difere do endereço usado pela Huawei |

## Fatos para a planilha de homologação (`docs/operations/SPEED_HOMOLOGACAO.md`)
- `DownloadDiagnostics` presente e `DiagnosticsState` gravável (modelo IGD:1, raiz `InternetGatewayDevice`); `UploadDiagnostics` presente, **não testado**.
- Caminho da WAN aceito em `Interface`: `InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.2` (a ÚNICA WAN da ZTE, serviço `INTERNET_TR069`, `Connected`; carrega também a gerência, como a da Huawei; aceita pelo responsável).
- A ZTE só alcança o nó de teste quando sua origem pública está na lista de origens permitidas; a natureza desse endereço (NAT compartilhado ou não) e quem mais o usa NÃO foram confirmadas.
- A ZTE não preenche `TotalBytesReceived` nem `TotalBytesSent` neste teste; a vazão deve vir de `TestBytesReceived` e do intervalo BOM→EOM, cujo relógio é do dispositivo.
- Connection Request da ZTE atende (HTTP 200) nas duas tarefas desta sonda.

## Próximo
Aceite de risco por escrito (`ACEITE-risco-3xx-f670l-2026-11-01.md`), inclusão da origem da ZTE na lista do nó, registro das operações de velocidade e um download real com autorização de uso único.
