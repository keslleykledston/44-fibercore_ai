# H1 (somente leitura) — `UploadDiagnostics` na ONT de bancada — 2026-10-31

Escopo: SOMENTE a ONT de bancada (Huawei EG8145V5 `V5R019C10S350`). **Nada foi escrito.** Uma tarefa `refreshObject` (leitura) do objeto `InternetGatewayDevice.UploadDiagnostics`, com Connection Request (HTTP 200 em 0,5 s), e leitura do cache do ACS. Sem endereço, credencial ou dado de cliente.

## Resultado
O objeto existe e o ACS passou a listar as suas folhas. Pelo critério do Edge (`speedRequired` do upload):
- `DiagnosticsState`: presente e **declarado gravável pelo aparelho** (o ACS guarda o indicador `_writable` que vem da resposta de `GetParameterNames`). **Aceitação de uma escrita não foi testada**: declarar gravável não prova que uma escrita é aceita ou aplicada.
- `BOMTime`, `EOMTime`, `TotalBytesSent`: presentes (somente leitura, como resultado).
- `TestBytesSent`: **ausente** (folha opcional para o Edge; o upload usa os outros contadores).
- Folhas de entrada **declaradas** graváveis (mesma ressalva): `UploadURL`, `TestFileLength`, `Interface`, `DSCP`, `EthernetPriority`, `NumberOfConnections`, `ProtocolVersion`, `TimeBasedTestDuration` e correlatas.
- `UploadTransports` = `HTTP,FTP`. Modelo de dados lido: `InternetGatewayDevice` (TR-098). **Não verificado:** se o objeto de upload também existe na raiz `Device` (o Edge exige raiz única e recusa se existir nas duas; essa checagem só roda na execução real).
- Valores atuais: estado `None` (nenhum upload feito), contadores zerados.

## Conclusão e limites
A gravabilidade foi inferida do que o aparelho declara, sem nenhuma escrita. **Capacidade identificada, não observada:** o aparelho oferece as folhas necessárias para o upload. Isso NÃO prova que o upload funciona nem que a ONT não redireciona (o aceite do risco de 3xx já vigente é por destino). Linha do registro: `speed_test_upload` = `supported` / `identified`, evidência este arquivo. O próximo passo (execução real do upload) exige a autorização de uso único com `--first-run`, que o responsável ainda não deu.
