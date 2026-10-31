# TR-143: adapter e cálculo correto

## Roots possíveis
- **Device:2**: `Device.IP.Diagnostics.DownloadDiagnostics.` e `Device.IP.Diagnostics.UploadDiagnostics.`
- **IGD:1**: `InternetGatewayDevice.DownloadDiagnostics.` e `InternetGatewayDevice.UploadDiagnostics.`
- Descobrir e confirmar os caminhos/objetos **por ONU e firmware**. Não misturar root IGD e Device no mesmo comando.

## Discovery mínimo
1. Inventário: modelo, fabricante, firmware, id de dispositivo ACS, modo bridge/roteado.
2. Presence: objetos `DownloadDiagnostics` / `UploadDiagnostics` e `DiagnosticsState`, `Interface`, URL, contadores e timestamps.
3. Permissões de escrita: metadata do GenieACS (`_writable` quando existente) e homologação prática controlada; presença sozinha não basta.
4. Capabilities: `...Capabilities.PerformanceDiagnostic.DownloadTransports`/`UploadTransports` quando presentes, mas alguns CPE não expõem corretamente. Homologação dita suporte real.
5. Escolher interface de serviço (ex: `Device.IP.Interface.N` ou WANIPConnection), **nunca hardcode N=2**.
6. Se root/interface não confirmados: `UNKNOWN` e não executar.

## Campos (Download)
| Campo | Uso |
|---|---|
| `Interface` | referência da WAN que transporta serviço |
| `DownloadURL` | URL GET aprovada |
| `DiagnosticsState` | escrever apenas `Requested`; resultado `Completed` ou `Error_*` |
| `BOMTime`, `EOMTime` | início/fim da transmissão |
| `TestBytesReceived` | bytes de tráfego da transação, incluindo overhead aplicável |
| `TotalBytesReceived` | bytes da interface; pode incluir concorrência |

**Cálculo primário:** `download_mbps = (TestBytesReceived * 8) / ((EOMTime - BOMTime).segundos * 1_000_000)`.

## Campos (Upload)
| Campo | Uso |
|---|---|
| `Interface` | referência da WAN que transporta serviço |
| `UploadURL` | URL HTTP PUT aprovada |
| `TestFileLength` | tamanho de dados transmitidos (bytes) |
| `DiagnosticsState` | escrever `Requested`, depois ler `Completed` ou erro |
| `BOMTime`, `EOMTime` | início/fim da transmissão |
| `TotalBytesSent` | tráfego total da interface, **não** equivale à transação em todas as versões |
| `TestBytesSent` | se existir em versões/modelos mais novos, preferir contador da transação |

**Cálculo primário (TR-143 legado, file-mode homologado):** `upload_mbps = (TestFileLength * 8) / ((EOMTime - BOMTime).segundos * 1_000_000)` quando o upload de todo arquivo tiver sido concluído e confirmado; se versão/report do CPE tiver `TestBytesSent` confiável, utilizá-lo preferencialmente.

**Opcional (não confundir):** throughput de interface = `TotalBytesSent * 8 / dt / 1e6`; pode carregar outros fluxos, usar como métrica auxiliar rotulada `throughput da interface`.

## Sanidade do resultado
- `DiagnosticsState` precisa ser `Completed` e atual (não reaproveitar estado anterior).
- `EOMTime > BOMTime`, duração positiva dentro de limites plausíveis; timestamps e contadores válidos.
- Falta de resultado confiável → `inconclusivo`, não 0 Mbps.
- Se dispositivo informa timestamps de relógio inconsistente, não inferir sucesso só pela diferença; exigir evidência correlacionada da execução atual.
- Tamanho de arquivo insuficiente / teste muito curto (ex: menos de 3 s) → `parcial` com aviso de baixa representatividade.
- `BOM/EOM` em diversas versões pode ter interpretação particular; registrar raw e adapter version.
- Download e upload são testes em sentidos opostos; não somar resultados.
- Latência, jitter e perda **não decorrem automaticamente** desses counters; integrar separadamente apenas se já houver diagnóstico ping/UDP echo validado.

## Exemplo setParameterValues (apenas laboratório)
```json
{
  "name": "setParameterValues",
  "parameterValues": [
    ["Device.IP.Diagnostics.DownloadDiagnostics.Interface", "Device.IP.Interface.1", "xsd:string"],
    ["Device.IP.Diagnostics.DownloadDiagnostics.DownloadURL", "http://192.0.2.10:8080/download/128MiB.bin", "xsd:string"],
    ["Device.IP.Diagnostics.DownloadDiagnostics.DiagnosticsState", "Requested", "xsd:string"]
  ]
}
```
`192.0.2.10` é endereço **documental**, não destino utilizável. **Obter interface real** do dispositivo antes de executar. Upload requer HTTP **PUT** no servidor e `TestFileLength` antes de `Requested`.

## Semântica NBI
- `POST /devices/<id>/tasks?connection_request` aceita tarefas; resposta `200` significa execução da tarefa naquela sessão, **não a conclusão do teste TR-143**; `202` significa pendente.
- `8 DIAGNOSTICS COMPLETE` é evento padrão de Inform da CPE, mas o NBI não possui necessariamente um endpoint nativo que entregue esse evento ao FiberCore; descobrir integração/evento já existente ou usar consulta de parâmetros controlada.
- Tarefas `refreshObject` e/ou `getParameterValues` para recuperar estado e contadores; verificar `_timestamp` (se disponível) e correlação temporal. Não escrever `Requested` novamente para ler resultado.

## Variações e limites
- HTTP/FTP dependem do CPE e de `DownloadTransports`/`UploadTransports`. MVP somente HTTP, se compatível.
- ONTs antigas podem gerar throughput inferior à capacidade da PON por CPU; o módulo não conclui automaticamente culpa da operadora.
- TR-143 não é sinônimo de Speedtest Ookla/iperf3; não criar pipeline simulando suporte inexistente.

Referências: https://cwmp-data-models.broadband-forum.org/tr-143-1-0-1.html ; https://cwmp-data-models.broadband-forum.org/tr-143-1-1-0.html ; https://docs.genieacs.com/en/latest/api-reference.html
