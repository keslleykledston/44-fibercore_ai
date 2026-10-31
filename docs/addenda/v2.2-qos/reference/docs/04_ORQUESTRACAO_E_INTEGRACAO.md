# Integração técnica / orquestração sem reconstrução

## Resumo da estratégia
Usar **orquestrador de diagnósticos e fila já implementados** no FiberCore. Um `QualityRun` é uma *suite*, não um serviço novo. Ele guarda links para `subRunIds` (PING/DNS/etc.) e `speedRunIds` do SD-001. Preferir estender o mecanismo de status/listagem já existente; os paths no contrato são somente sugestão.

```text
ONT sidebar [RÁPIDO/COMPLETO] -> API atual autenticada -> job de diagnóstico atual
  -> Capability Registry (modelo + fw + WAN de serviço + last verification)
  -> Edge Connector outbound do tenant -> GenieACS NBI -> CPE (CWMP)
  <- leituras com timestamps e status de job <- normalização e persistência atuais
  -> QoS-001 interpreta (sem ação de IA) -> resumo no drawer -> Copilot somente read-only
COMPLETO -> referência a runs do SD-001 (sem reimplementar TR-143) -> agregado
```

## Sequência de um RÁPIDO
1. Autorizar `diagnostics.quality.run` (ou permissão existente) + validar tenant/device/feature flag, idempotência.
2. Ler telemetria já recente (ACS/OLT/monitoramento existentes) SEM exigir varredura geral. Se houver métrica expirada e permitida: `getParameterValues`/`refreshObject` direcionado e com orçamento de requests.
3. Resolver interfaces de serviço por configuração validada/capability; proibir usar WAN ACS de gerenciamento como prova da conexão do assinante.
4. Se PING homologado, testar destino IP de CORE aprovado, usando poucos pacotes (ex. 5, timeout 1000 ms). Parametrização + `DiagnosticsState=Requested` numa única chamada `setParameterValues`. DNS curto para hostname aprovado somente se perfil homologado.
5. `POST task` no NBI pode retornar HTTP `200` (tarefa executada) ou `202` (enfileirada). NENHUM indica conclusão do diagnóstico; acompanhar Inform `8 DIAGNOSTICS COMPLETE`, resultado de parâmetros e proveniência da execução, conforme infraestrutura existente.
6. Recolher estado terminal/contadores e marcar evidência de frescor. Em falha de ping, preservar telemetria válida e retornar `partial`/`inconclusive` quando apropriado.
7. Persistir resultado agregado e publicar evento interno existente, sem criar broker novo.

## Sequência de um COMPLETO
1. Confirmar impacto e destinos desejados (`CORE`, `INTERNET`, no máximo 2), com limites de PON/tenant já usados pelo SD-001.
2. Rodar RÁPIDO; em seguida **invocar serviço atual** `SpeedDiagnostics.startRun(target)` de forma serial. Reusar `runId`/status/erros/limites existentes; não chamar TR-143 direto por caminho alternativo.
3. Se firmware suportar e operador habilitar `trace`, executar traceroute após banda, não em paralelo com outros diagnósticos no mesmo CPE.
4. Quando speed não suportado, concluir a parte rápida e registrar `speed=not_supported`, não falhar indiscriminadamente.
5. Estado final da suite: `completed`, `partial`, `failed`, `timeout` com detalhes por métrica. `partial` não é uma medição inválida dos componentes válidos.

## Tarefas de exemplo (GenieACS)
**Ping TR-181** (somente laboratório e interface realmente descoberta):
```json
{
  "name":"setParameterValues",
  "parameterValues":[
    ["Device.IP.Diagnostics.IPPing.Interface","Device.IP.Interface.1","xsd:string"],
    ["Device.IP.Diagnostics.IPPing.Host","192.0.2.10","xsd:string"],
    ["Device.IP.Diagnostics.IPPing.NumberOfRepetitions",5,"xsd:unsignedInt"],
    ["Device.IP.Diagnostics.IPPing.Timeout",1000,"xsd:unsignedInt"],
    ["Device.IP.Diagnostics.IPPing.DiagnosticsState","Requested","xsd:string"]
  ]
}
```
**DNS TR-181** (interface especificável ou não conforme objeto/versão):
```json
{
  "name":"setParameterValues",
  "parameterValues":[
    ["Device.DNS.Diagnostics.NSLookupDiagnostics.HostName","diagnostic.example.net","xsd:string"],
    ["Device.DNS.Diagnostics.NSLookupDiagnostics.NumberOfRepetitions",2,"xsd:unsignedInt"],
    ["Device.DNS.Diagnostics.NSLookupDiagnostics.DiagnosticsState","Requested","xsd:string"]
  ]
}
```
`192.0.2.10` e `diagnostic.example.net` são **valores ilustrativos reservados**, não destinos de teste de produção.

## Conclusão confiável e concorrência
- Adquirir `deviceDiagnosticLock` por CPE para operações que sobrescrevem o mesmo objeto `DiagnosticsState`, inclusive SD-001. Nunca permitir dois ping simultâneos no mesmo objeto.
- Registrar `requestedAt`, `nbiTaskId`, `queued/dispatched`, snapshot anterior, `lastInformAt` e, quando possível, o evento `8`, além dos parâmetros refrescados **após** o pedido. Ausência de provas → `inconclusive`, nunca reutilizar `Complete` antigo.
- Não reescrever `Requested` em polling. Usar o mecanismo de entrega/eventos existente com timeout e sem busy loop.
- Não considerar `getParameterValues` executado equivalente a teste novo; mapear timestamps dos parâmetros e estados observados.
- Nunca presumir cancelamento do teste dentro da ONT apenas pela remoção do job no servidor.

## Política de erros
- `CWMP_NOT_SUPPORTED`, `WAN_UNVERIFIED`, `ACS_OFFLINE`, `TASK_QUEUED`, `DIAGNOSTIC_TIMEOUT`, `STALE_RESULT`, `CPE_ERROR`, `ENDPOINT_UNREACHABLE`, `CAPABILITY_UNVERIFIED`, `NOT_APPLICABLE`.
- NBI/Edge fora → erro localizado, sem travar ONU 360 / telas gerais.
- Sem WAN de serviço: pode exibir status/telemetria gerencial *rotulada*, mas não executar nem atribuir ping/banda ao serviço contratado.

## Dados e persistência
- Aproveitar modelo de job/resultado existente; se necessário, acrescentar um registro de suite que relaciona jobs, `metrics` normalizadas, `hypotheses` e versão do perfil. Migração somente aditiva e com RLS/tenant existentes.
- Reaproveitar histórico e auditoria atuais; não armazenar IP público, SSID, MAC de dispositivos de cliente ou destino arbitrário quando não necessário.
