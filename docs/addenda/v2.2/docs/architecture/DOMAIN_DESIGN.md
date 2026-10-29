# Modularidade e contratos v2.2

**Manter FastAPI monólito modular.** Não acrescentar 10 containers para novos nomes. Bounded contexts lógicos: `inventory`, `cpe-unified`, `customer-context`, `capability-registry`, `data-quality`, `diagnostics`, `noc-events`, `qoe`, `network-topology`, `automation-jobs`, `help-center` (embutido Next.js), `copilot` (opcional). Cada módulo tem migration, API, eventos, health, feature flag, owner, docs e comportamento degradado.

## Modelagem aditiva sugerida
- `device_capabilities(tenant_id,device_id,model,firmware,protocol,operation,support_status,certification,verified_at,evidence_ref)`; unique em escopo apropriado.
- `observations(tenant_id,device_id,source,field,observed_at,ingested_at,quality,value,unit)`; particionar por tempo/tenant conforme volume.
- `customer_context_projection(tenant_id,customer_id,onu_id,cpe_id,erp_contract_id,revision,calculated_at)`; pode ser view materializada, não fonte comercial.
- `diagnostic_rule_versions(rule_id,version,conditions,outputs,confidence_basis,enabled)` + `diagnostic_runs(tenant_id,run_id,subject_id,observations_used,rule_version,conclusions,created_at)`.
- `network_links(tenant_id,source_entity_id,target_entity_id,evidence,confidence,confirmed_by,observed_at)` com resolução manual de ambiguidades.
- `qoe_score_runs(tenant_id,entity_id,score_type,algorithm_version,score,coverage,status,evidence_refs,observed_at)`.
- `workflow_definitions(version,id,intent_schema,risk,capability_requirements)` e executores já existentes em `jobs` — não criar duplicado.

## Contratos e consistência
- `GET /v1/customers/{id}/context`: agregação read-only; fontes separadas, observed_at, quality, URL interna de evidência; conteúdo restrito por permissões.
- `GET /v1/devices/{id}/capabilities`: unknown→observed→certified, com notas e firmware.
- `POST /v1/diagnostics/runs`: cria diagnóstico read-only e persistência auditável; JSON de conclusão com status observed/inferred/unknown.
- `GET /v1/network/topology`: suporte tree com evidência; opção de nível/site.
- `GET /v1/qoe/{id}`: retorna score ou `insufficient_data`, jamais 0 imputado.
- `GET /v1/workflow-definitions`, `POST /v1/workflow-previews`: não executa comandos.

## Eventos sugeridos
`device.capabilities.changed.v1`, `device.observation.ingested.v1`, `customer.context.updated.v1`, `incident.correlation.updated.v1`, `diagnostic.run.completed.v1`, `qoe.score.computed.v1`. Envelope obrigatório inclui `tenant_id`, `event_id`, `schema_version`, `source`, `occurred_at`, `ingested_at`, `correlation_id`, subject id, quality. Sem segredos.

## Semântica de falha
Core read-only continua se GenieACS/USP/LLM/ERP falharem; contexto marcado stale/partial; nunca dar nota ou dizer ONU offline devido ao Edge offline. Sem retry cego de escrita; workflows têm locks, TTL, aprovação e pós-check.
