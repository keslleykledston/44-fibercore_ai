# v2.2 — Contrato reconciliado

`contracts/fibercore-v2.2-reconciled.openapi.yaml` reconcilia o contrato proposto (`contracts/fibercore-v2.2-additive.openapi.yaml`, **mantido intacto**) com a API real. Regras: caminhos sem prefixo `/api` (o proxy o remove, ADR-0012); `X-Workspace-ID` opcional (ver C-02); POST que cria devolve 201; cada operação traz `x-fc22-id` e `x-status` (`implemented` | `planned`). O teste `tests/validate_addendum_v22.py` exige que `implemented` ⇔ o caminho existe em `contracts/fibercore-v2.openapi.yaml` (nada declarado pronto sem estar no contrato vigente) e que nenhum `planned` colida com um caminho já existente.

| Proposto | Reconciliado | Estado |
|---|---|---|
| `GET /customers/{id}/context` | `GET /v1/customers/{customer_id}/context` | planned (FC22-004) |
| `GET /devices/{id}/capabilities` | `GET /v1/devices/{device_id}/capabilities` (OLT ou CPE) | planned → implemented no PR 35 |
| `POST /diagnostics/runs` (200) | `POST /v1/diagnostics/runs` (201 + `run_id`) | planned (FC22-006) |
| `GET /network/topology` | `GET /v1/network/topology` | planned (FC22-010) |
| `GET /qoe/{id}` | `GET /v1/qoe/{subject_id}` (`score: null` + `insufficient_data` até haver dado) | planned (FC22-011/012) |
| `GET /workflow-definitions` | `GET /v1/workflow-definitions` (catálogo; execução = `/v1/jobs`) | planned (FC22-014) |
| `POST /workflow-previews` | **removido**: usar `POST /v1/jobs/preview` | existe |

## Eventos (envelope `contracts/events.v2.2.schema.json`)
O outbox guarda `aggregate_type`, `aggregate_id`, `event_type`, `schema_version`, `payload`; o envelope v2.2 é montado na publicação: `subject_id = aggregate_id`, `type = event_type` (sem sufixo `.v1`; versão em `schema_version`), `source` e `quality` obrigatórios no payload dos novos eventos, `tenant_id` sempre. Nenhum segredo nem PII em payload.
