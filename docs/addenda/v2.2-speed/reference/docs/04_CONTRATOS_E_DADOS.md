# Contratos, persistência e integração

## Estratégia de integração
- Verificar primeiro a API REST, DTOs, eventos, workers, auth e persistência **existentes** do FiberCore.
- `contracts/openapi.fragment.yaml` é **proposta**, não uma rota que deve ser criada em duplicidade se a API atual já permite iniciar testes.
- Fluxo de status e resultados tem que estar contido no tenant; API same-origin `/api/v1` já adotada.
- NBI somente no Edge Connector no host do GenieACS; não enviar credenciais do ACS ao browser nem ao copiloto.

## Endpoints lógicos propostos (adaptar à convenção real)
- `GET /api/v1/devices/{deviceId}/diagnostics/speed/capabilities`: disponibilidade de DL/UL, método, interface, motivos de bloqueio, destinos possíveis.
- `POST /api/v1/devices/{deviceId}/diagnostics/speed/runs`: `{target:"CORE"|"INTERNET"}`. Sem URL livre e sem acesso direto ao NBI.
- `GET /api/v1/devices/{deviceId}/diagnostics/speed/runs/{runId}`: estado/progresso/resultados.
- `GET /api/v1/devices/{deviceId}/diagnostics/speed/runs?limit=10`: últimas medições.

## DTO de resultado
```json
{
  "id": "spd_0001",
  "deviceId": "ont_001",
  "target": "CORE",
  "method": "TR143_HTTP",
  "state": "completed",
  "quality": "valid",
  "downloadMbps": 482.4,
  "uploadMbps": 245.8,
  "wanInterface": "Device.IP.Interface.1",
  "planMbps": {"download": 500, "upload": 250, "source": "ERP_CONFIRMED"},
  "startedAt": "2026-10-31T12:00:00Z",
  "finishedAt": "2026-10-31T12:00:40Z",
  "warnings": ["Mede a WAN da ONT; não mede Wi-Fi/LAN"]
}
```
*Dados sintéticos; convenção de IDs adaptável.*

## DB: mínimo lógico
Uma tabela de `speed_test_runs` se nenhum job de diagnóstico existente puder ser estendido; preferir campo/tipo no job atual e tabela para resultados específicos. Campos: id, tenant_id, device_id, actor_id, target, method, requested_utc, started_utc, ended_utc, state, quality, support_reason, iface, dl/ul Mbps, raw counters normalizados, evidence_time, endpoint_logical_name, model/firmware, plan snapshot, warnings, error_code, error_message seguro, job ids do Edge/NBI, version de adapter.

Sem armazenar credenciais, URL com query token, payload de upload, IP pessoal desnecessário ou conteúdo de assinante. Isolamento via autorização server-side e RLS existente. Banco PostgreSQL FiberCore **nunca** conectado/migrado ao Mongo GenieACS.

## Contrato de capacidade
- `supportsDownload`, `supportsUpload`: boolean somente quando homologado; `unknown` em outro campo explicitamente.
- `status`: `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, `UNKNOWN`.
- `wanInterfaceVerified`: boolean.
- `targets`: `CORE`, `INTERNET` quando endpoint pronto + rota comprovada.
- `blockers[]`: lista com códigos estáveis (`NO_TR143`, `BRIDGE_NO_SERVICE_WAN`, `NOT_HOMOLOGATED`, `NO_TARGET`, `NO_PERMISSION`, `DEVICE_OFFLINE`, `WAN_UNVERIFIED`).

## Código de erros e sinais
- `CPE_UNSUPPORTED`, `CPE_FAULT`, `CPE_OFFLINE`, `EDGE_UNREACHABLE`, `ACS_TASK_PENDING`, `DIAGNOSTICS_TIMEOUT`, `RESULT_STALE`, `COUNTERS_INVALID`, `WAN_UNVERIFIED`, `TEST_NODE_UNREACHABLE`, `RESOURCE_BUSY`, `TENANT_FORBIDDEN`.
- Nunca renderizar um fault operacional como 0 Mbps.
- APIs respondem `409` para slot ocupado, `422` para capacidades/wan incompatíveis, `403` permissão/tenant, `202` job aceito, `404` id fora do tenant; preferir padrões já existentes.

## Evolução não obrigatória
Plano nominal do HubSoft pode ser usado se o integração/tenant já tiver esse dado com origem verificável. Não bloquear Speed Diagnostics sem ERP. Não criar integrações IXC/SGP/HubSoft como parte deste PR.
