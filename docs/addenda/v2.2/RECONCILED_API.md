# v2.2 — Contrato reconciliado

`contracts/fibercore-v2.2-reconciled.openapi.yaml` reconcilia o contrato proposto (`contracts/fibercore-v2.2-additive.openapi.yaml`, **mantido intacto**) com a API **real**.

## Prefixo: público × interno
Os contratos listam caminhos relativos ao servidor público **`/api/v1`**. O core serve em **`/v1`**; o proxy remove só o `/api` (`uri strip_prefix /api`, `infra/deploy/Caddyfile.upstream`, ADR-0012). Nos testes, o caminho interno é `/v1` + caminho do contrato.

## Regras e como são verificadas (`tests/validate_addendum_v22.py`)
- `x-status: implemented` ⇔ a rota **existe no código** (app FastAPI importado); `planned` ⇒ a rota **não** existe. Não basta constar em outro YAML.
- Deriva contrato × código: o conjunto "documentado e não implementado" tem de ser **exatamente** a lista conhecida (C-19 da GAP); rota no código sem contrato é falha.
- Toda operação do contrato vigente sobre `/capabilities` ou `/jobs/preview` tem de aparecer no reconciliado.

| Proposto | Reconciliado (caminho público) | Estado |
|---|---|---|
| `GET /customers/{id}/context` | `GET /customers/{customer_id}/context` | planned (FC22-004) |
| `GET /devices/{id}/capabilities` | **descartado** (não há recurso `devices`) → `GET /cpes/{cpeId}/capabilities` (**já documentada no contrato vigente, sem handler**) + `GET /olts/{oltId}/capabilities` | planned → PR 35 |
| `POST /diagnostics/runs` (200) | `POST /diagnostics/runs` (201 + `run_id`) | planned (FC22-006) |
| `GET /network/topology` | idem | planned (FC22-010) |
| `GET /qoe/{id}` | `GET /qoe/{subject_id}` (`score: null` + `insufficient_data` até haver dado) | planned (FC22-011/012) |
| `GET /workflow-definitions` | idem (catálogo; execução = jobs) | planned (FC22-014) |
| `POST /workflow-previews` | **descartado**: `POST /jobs/preview` **já existe** | implemented |

## Eventos (envelope `contracts/events.v2.2.schema.json`)
O outbox guarda `aggregate_type`, `aggregate_id`, `event_type`, `schema_version`, `payload`; o envelope v2.2 é montado na publicação: `subject_id = aggregate_id`, `type = event_type` (sem sufixo `.v1`; versão em `schema_version`), `source` e `quality` obrigatórios nos novos eventos, `tenant_id` sempre. Sem segredo nem PII no payload.
