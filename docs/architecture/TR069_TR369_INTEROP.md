# Gerência CPE dual-stack: TR-069 + TR-369

## Limites de responsabilidade

| Aspecto | TR-069 | TR-369 / USP |
|---|---|---|
| Motor | GenieACS existente no site do ISP | USP Controller independente e homologado |
| Interface FiberCore | Edge -> API NBI privada | Edge/service -> REST/gRPC SDK específico do controlador |
| Comunicação CPE | CWMP iniciado normalmente por Inform; Connection Request se possível | Agent ↔ Controller sobre MQTT/WebSocket/transportes homologados |
| Modelo de dados | TR-098 (`InternetGatewayDevice.*`) ou TR-181 (`Device.*`) conforme dispositivo | TR-181/USP (`Device.*`) conforme dispositivo |
| Estado assíncrono | task queued, pendente de Inform, confirmed e pós-check | RPC ack, notifications, resultado e pós-check |
| Certificação | por fabricante/modelo/firmware/operação | por fabricante/modelo/firmware/MTP/operação |

## Estado canônico de cada parâmetro

`name` (ex.: `wifi.ssid`), `raw_path`, `raw_protocol`, `source_connector`, `raw_type`, `value_masked`, `writable`, `observed_at`, `ingested_at`, `confidence`, `capability_certification`. Valores conflitantes não são fundidos automaticamente: mostrar origem e data; escolher fonte read com política e preferência por dado mais recente confiável. Não substituir passphrase com string mascarada.

## Seleção do transporte para operação

1. Resolver dispositivo por `(tenant_id, cpe_id)` e bindings comprovadas.
2. Localizar capability com certificação por firmware, privilégios e disponibilidade atual.
3. Verificar política por tenant e preferências por feature (ex.: `wifi.ssid.write -> tr369`; `reboot -> tr069` apenas se homologados), não escolher pelo simples fato de estar online.
4. Adquirir lock por `(tenant_id,cpe_id,capability_scope)` antes do dispatch; registrar protocolo escolhido e policy version.
5. Aplicar preview/aprovação conforme risco, submeter comando tipado com TTL e verificar consequência via leitura fresca.
6. Em timeout, reconciliar a tarefa original; **nunca** fazer failover automático de um write de USP para CWMP.

## Controles específicos do GenieACS

- Não recriar GenieACS e não editar scripts/presets sem autorização formal.
- GET `/devices` com projection/query restritas; cadência, paginação e rate limit controlados. Inventário com cronograma que não degrade NBI.
- NBI POST `/devices/:id/tasks?connection_request` somente no executor aprovado. 200 pode indicar execução; 202 enfileirado. Em ambos, requer pós-check de parâmetro/estado antes de `verified`.
- NBI deve permanecer em rede administrativa privada, com proteção adicional do Edge e autenticação/restrições de firewall conforme deployment.

## Prova de homologação USP Controller

Controller candidato OB-USPC só após ensaio de MQTT/WS, identidade, trust store/certificados, REST API, multi-tenancy/isolation, escalabilidade, persistência e recuperação, auditabilidade, testes com USP Agents reais, licenciamento e capacidade operacional. O projeto de referência tem ressalva de uso em produção em documentação histórica do BBF; não presumir HA. Se falhar qualquer gate de segurança, manter `usp-tr369` desativado até escolher alternativa ou implementar controle adequado.
