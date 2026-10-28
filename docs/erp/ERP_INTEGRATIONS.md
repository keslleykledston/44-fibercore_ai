# ERP Hub — arquitetura e integração incremental

## Conceito

Adapter por ERP sem acoplar modelo interno: `csv`, `generic_rest`, `ixc`, `sgp`, `mk_solutions`, `hubsoft`, `voalle`, `radiusnet`, `topsapp`. Terceiros em estado `planned` até contrato API/documentação, credenciais e fixtures autorizadas; não inventar endpoints específicos do ERP.

## Modelo canônico

`external_customer_id`, `external_contract_id`, `display_name`, `document_masked`, `customer_status`, `contract_status`, `financial_status`, `plan_code`, `plan_speed_mbps`, `monthly_amount` (opcional), `login_identifier`, `installation_address` (restrito), `city`, `neighborhood`, `coordinates` (opcional), `onu_serial`, `ont_mac`, `cto_id`, `cto_port`, `ticket_ids`, `source_updated_at`. Origem possui `erp_id`, `tenant`, `source_record_id`, `revision`.

Distinguir o status da assinatura do status financeiro e status da ONU; jamais concluir que inadimplente equivale a ONU desligada.

## APIs e webhooks

- `POST /v1/integrations/erp` cadastra alias, tipo e referência ao segredo (nunca devolve credencial).
- `POST /v1/integrations/erp/{id}/test` testa conectividade de forma read-only.
- `POST /v1/integrations/erp/{id}/sync` inicia job com limite e `cursor`, retorna `202 job_id`.
- `GET /v1/integrations/erp/{id}/runs` expõe dados de progresso/erros redigidos.
- `GET /v1/customers`, `/v1/contracts`, `/v1/associations`, `/v1/associations/conflicts`.
- `POST /v1/associations/suggest` retorna evidências + score explicável; `POST /v1/associations/{id}/approve` exige permissão.
- Webhooks de saída tipados/signed HMAC/Idempotency-Key (`device.offline`, `incident.opened`, `association.conflict`, `job.completed`), com retry controlado e DLQ.

## Sync

Polling incremental se API permitir, snapshot inicial paginado e idempotente, delta via webhooks quando suportado, validação de schemas, backoff em 429/5xx, cursor persistido, mapping configurável, `last_success_at`, limites por tenant, **sem fazer writeback automático ao ERP no piloto**. Conflitos ficam pendentes para avaliação humana. Dados brutos sensíveis ficam restritos com TTL, e jamais em prompts.

## Primeira entrega

CSV + REST genérica documentada + fixtures; decidir qual ERP concreto é primeiro após disponibilidade de acesso e contrato API. IXC/SGP prioridade de descoberta, não inventar conformidade nem suporte sem homologação.
