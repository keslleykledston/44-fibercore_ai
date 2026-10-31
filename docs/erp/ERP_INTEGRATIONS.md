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

## v2.3.1 — HubSoft primeiro (ADR-0033)
Ordem de homologação: **HubSoft (P0) → IXC (P1) → SGP (P2)**. Entregue (somente contra mocks, NÃO homologado): registro de provedores, tabela `erp_connections` (migração 0030), `/v1/integrations/erp` (listar, criar, testar, ligar, desligar), segredo por referência em arquivo 0600 por tenant, guarda de URL/SSRF e token OAuth com cache e política 401/403/429/5xx. Próximo: HS-03 (consulta de cliente, valores de `busca` confirmados na instância autorizada), HS-04 a HS-08. Operação: criar `ERP_SECRETS_DIR/<tenant_id>/<ref>.json` (0600; `client_id`, `client_secret`, `username`, `password`) e definir `ERP_ALLOWED_HOSTS`; ligar o flag `erp_hubsoft` do tenant (`app.cli feature-set`). Nunca enviar segredo por chat.
