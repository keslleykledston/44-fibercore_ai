# Matriz RBAC (gerada)

> GERADA por `scripts/gen_rbac_matrix.py` a partir do catálogo (`app/core/permissions.py`), dos papéis (`app/core/security.py`) e das rotas reais. Não edite à mão: o teste `test_rbac_inventory.py` falha se este arquivo divergir do código. Decisão e plano: ADR-0031.

## Permissões

| Permissão | Risco | MFA recente | Escopável | O que permite |
|---|---|---|---|---|
| `tenant:read` | R0 | não | não | Ver o próprio provedor e seus dados básicos |
| `inventory:read` | R0 | não | sim | Ver OLTs, ONUs, CPEs, relatórios de rede e capacidades |
| `inventory:write` | R2 | não | não | Enviar inventário e estado (somente contas de serviço do Edge) |
| `incidents:read` | R0 | não | sim | Ver incidentes e o NOC |
| `incidents:ack` | R2 | não | sim | Reconhecer um incidente |
| `customers:read` | R1 | não | não | Ver assinantes (dado pessoal; toda visualização é auditada) |
| `customers:import` | R1 | sim | não | Importar clientes do ERP |
| `associations:review` | R2 | não | não | Revisar vínculos ONU↔cliente e ONU↔CPE |
| `jobs:read` | R0 | não | não | Ver operações solicitadas |
| `jobs:request` | R2 | não | sim | Solicitar uma operação em equipamento |
| `jobs:approve` | R3 | sim | sim | Aprovar uma operação em equipamento |
| `jobs:execute` | R3 | não | não | Executar operações aprovadas (somente contas de serviço do Edge) |
| `devices:act:reboot_cpe` | R2 | não | sim | Pedir, pela tela do CPE, o reinício do equipamento do assinante (nasce bloqueado até a homologação) |
| `devices:act:set_wifi_ssid` | R2 | não | sim | Pedir, pela tela do CPE, a troca do nome do Wi-Fi (nasce bloqueado até a homologação) |
| `bench:authorize` | R3 | sim | não | Autorizar UMA manobra de bancada (uso único, janela curta, só o alvo de bancada); o autorizador não pode ser quem pede nem quem aprova |
| `olt_query:run` | R0 | não | sim | Pedir uma consulta somente leitura à OLT (catálogo fechado; a fila e a cota protegem o equipamento) |
| `erp:manage` | R3 | sim | não | Cadastrar e desativar a conexão com o ERP do provedor (guarda só a referência do segredo, nunca o segredo) |
| `erp:test` | R2 | não | não | Testar a conexão com o ERP (autentica e nada mais; somente leitura) |
| `diagnostics:run` | R0 | não | sim | Rodar diagnósticos (somente leitura) |
| `members:read` | R1 | não | não | Ver os membros do provedor e o estado do MFA de cada um |
| `members:manage` | R3 | sim | não | Atribuir e alterar o papel dos membros (dentro do que o papel de quem atribui permite) |
| `platform:delegate` | R3 | sim | não | Conceder e revogar o acesso temporário (até 8 h, com motivo) do suporte da plataforma a este provedor |
| `roles:read` | R0 | não | não | Ver os papéis do sistema e as permissões de cada um |
| `members:mfa_reset` | R3 | sim | não | Redefinir o MFA de outro membro |
| `edge:read` | R0 | não | não | Ver os Edges do provedor |
| `edge:heartbeat` | R0 | não | não | Enviar batimento (somente contas de serviço do Edge) |
| `audit:read` | R1 | não | não | Ver o registro de auditoria |

## Papéis × permissões

| Permissão | `isp_admin` | `engineer` | `noc_n2` | `noc_n1` | `support` | `auditor` | `platform_support` | `edge_agent` | `access_manager` |
|---|---|---|---|---|---|---|---|---|---|
| `tenant:read` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  | ✔ |
| `inventory:read` | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `inventory:write` |  |  |  |  |  |  |  | ✔ |  |
| `incidents:read` | ✔ | ✔ | ✔ | ✔ |  |  |  |  |  |
| `incidents:ack` | ✔ | ✔ | ✔ |  |  |  |  |  |  |
| `customers:read` | ✔ | ✔ | ✔ |  | ✔ |  |  |  |  |
| `customers:import` | ✔ |  |  |  |  |  |  |  |  |
| `associations:review` | ✔ | ✔ |  |  |  |  |  |  |  |
| `jobs:read` | ✔ | ✔ | ✔ |  |  |  |  |  |  |
| `jobs:request` | ✔ | ✔ | ✔ |  |  |  |  |  |  |
| `jobs:approve` | ✔ |  |  |  |  |  |  |  |  |
| `jobs:execute` |  |  |  |  |  |  |  | ✔ |  |
| `devices:act:reboot_cpe` | ✔ | ✔ | ✔ |  |  |  |  |  |  |
| `devices:act:set_wifi_ssid` | ✔ | ✔ |  |  |  |  |  |  |  |
| `bench:authorize` | ✔ | ✔ | ✔ |  |  |  |  |  |  |
| `olt_query:run` | ✔ | ✔ | ✔ |  |  |  |  |  |  |
| `erp:manage` | ✔ |  |  |  |  |  |  |  |  |
| `erp:test` | ✔ |  |  |  |  |  |  |  |  |
| `diagnostics:run` | ✔ | ✔ | ✔ |  |  |  |  |  |  |
| `members:read` | ✔ |  |  |  |  |  |  |  | ✔ |
| `members:manage` | ✔ |  |  |  |  |  |  |  | ✔ |
| `platform:delegate` | ✔ |  |  |  |  |  |  |  |  |
| `roles:read` | ✔ |  |  |  |  |  |  |  | ✔ |
| `members:mfa_reset` | ✔ |  |  |  |  |  |  |  |  |
| `edge:read` | ✔ | ✔ | ✔ |  |  |  |  |  |  |
| `edge:heartbeat` |  |  |  |  |  |  |  | ✔ |  |
| `audit:read` | ✔ |  |  |  |  | ✔ |  |  | ✔ |

## Rotas × permissão

| Método | Rota | Exige |
|---|---|---|
| GET | `/livez` | (pública ou usa credencial no corpo) |
| GET | `/readyz` | (pública ou usa credencial no corpo) |
| GET | `/v1/associations` | `customers:read` |
| POST | `/v1/associations/{assoc_id}/approve` | `associations:review` |
| POST | `/v1/associations/{assoc_id}/reject` | `associations:review` |
| GET | `/v1/audit` | `audit:read` |
| POST | `/v1/auth/logout` | (pública ou usa credencial no corpo) |
| GET | `/v1/auth/me` | (sessão válida, sem permissão) |
| POST | `/v1/auth/mfa/activate` | (autentica o token da própria conta) |
| POST | `/v1/auth/mfa/disable` | (autentica o token da própria conta) |
| POST | `/v1/auth/mfa/enroll` | (autentica o token da própria conta) |
| POST | `/v1/auth/mfa/recovery-codes` | (autentica o token da própria conta) |
| GET | `/v1/auth/mfa/status` | (autentica o token da própria conta) |
| POST | `/v1/auth/mfa/step-up` | (autentica o token da própria conta) |
| POST | `/v1/auth/mfa/verify` | (pública ou usa credencial no corpo) |
| POST | `/v1/auth/password` | (autentica o token da própria conta) |
| POST | `/v1/auth/refresh` | (pública ou usa credencial no corpo) |
| POST | `/v1/auth/service-token` | (pública ou usa credencial no corpo) |
| POST | `/v1/auth/token` | (pública ou usa credencial no corpo) |
| GET | `/v1/auth/workspaces` | (autentica o token da própria conta) |
| GET | `/v1/bench/authorizations` | `jobs:read` |
| POST | `/v1/bench/authorizations` | `bench:authorize` |
| DELETE | `/v1/bench/authorizations/{authorization_id}` | `bench:authorize` |
| GET | `/v1/cpes` | `inventory:read` |
| GET | `/v1/cpes/{cpe_id}` | `inventory:read` |
| GET | `/v1/cpes/{cpe_id}/actions` | `inventory:read` |
| POST | `/v1/cpes/{cpe_id}/actions/reboot_cpe` | `devices:act:reboot_cpe` |
| POST | `/v1/cpes/{cpe_id}/actions/set_wifi_ssid` | `devices:act:set_wifi_ssid` |
| GET | `/v1/cpes/{cpe_id}/capabilities` | `inventory:read` |
| GET | `/v1/cpes/{cpe_id}/state` | `inventory:read` |
| GET | `/v1/customers` | `customers:read` |
| GET | `/v1/customers/{customer_id}/context` | `customers:read` |
| POST | `/v1/diagnostics/jobs` | `diagnostics:run` |
| GET | `/v1/diagnostics/jobs/{job_id}` | `incidents:read` |
| GET | `/v1/diagnostics/rules` | `incidents:read` |
| POST | `/v1/diagnostics/runs` | `diagnostics:run` |
| GET | `/v1/diagnostics/runs/{run_id}` | `incidents:read` |
| POST | `/v1/edge/cpe-snapshots` | `inventory:write` |
| POST | `/v1/edge/cpe-state` | `inventory:write` |
| POST | `/v1/edge/heartbeat` | `edge:heartbeat` |
| GET | `/v1/edge/jobs/next` | `jobs:execute` |
| POST | `/v1/edge/jobs/{job_id}/result` | `jobs:execute` |
| POST | `/v1/edge/olt-snapshots` | `inventory:write` |
| GET | `/v1/edges` | `edge:read` |
| POST | `/v1/erp/import-csv` | `customers:import` |
| GET | `/v1/incidents` | `incidents:read` |
| GET | `/v1/incidents/{incident_id}` | `incidents:read` |
| POST | `/v1/incidents/{incident_id}/ack` | `incidents:ack` |
| GET | `/v1/integrations/erp` | `erp:test` |
| POST | `/v1/integrations/erp` | `erp:manage` |
| POST | `/v1/integrations/erp/{connection_id}/disable` | `erp:manage` |
| POST | `/v1/integrations/erp/{connection_id}/enable` | `erp:manage` |
| POST | `/v1/integrations/erp/{connection_id}/test` | `erp:test` |
| GET | `/v1/invites/{token}` | (pública ou usa credencial no corpo) |
| POST | `/v1/invites/{token}/accept` | (pública ou usa credencial no corpo) |
| GET | `/v1/jobs` | `jobs:read` |
| POST | `/v1/jobs/preview` | `jobs:request` |
| GET | `/v1/jobs/{job_id}` | `jobs:read` |
| POST | `/v1/jobs/{job_id}/approve` | `jobs:approve` |
| POST | `/v1/jobs/{job_id}/cancel` | `jobs:request` |
| POST | `/v1/jobs/{job_id}/submit` | `jobs:request` |
| GET | `/v1/members` | `members:read` |
| GET | `/v1/members/role-history` | `audit:read` |
| POST | `/v1/members/{user_id}/mfa/reset` | `members:mfa_reset` |
| PUT | `/v1/members/{user_id}/role` | `members:manage` |
| GET | `/v1/olts` | `inventory:read` |
| GET | `/v1/olts/{olt_id}/capabilities` | `inventory:read` |
| GET | `/v1/olts/{olt_id}/queries` | `inventory:read` |
| POST | `/v1/olts/{olt_id}/queries/{query_id}` | `olt_query:run` |
| GET | `/v1/olts/{olt_id}/queries/{query_id}/latest` | `olt_query:run` |
| GET | `/v1/onu-cpe-links` | `inventory:read` |
| POST | `/v1/onu-cpe-links/suggest` | `associations:review` |
| POST | `/v1/onu-cpe-links/{link_id}/confirm` | `associations:review` |
| POST | `/v1/onu-cpe-links/{link_id}/reject` | `associations:review` |
| GET | `/v1/onus` | `inventory:read` |
| GET | `/v1/onus/offline` | `inventory:read` |
| GET | `/v1/onus/unstable` | `inventory:read` |
| GET | `/v1/onus/{onu_id}` | `inventory:read` |
| GET | `/v1/onus/{onu_id}/customer` | `customers:read` |
| GET | `/v1/onus/{onu_id}/history` | `inventory:read` |
| GET | `/v1/platform-delegations` | `members:read` |
| POST | `/v1/platform-delegations` | `platform:delegate` |
| DELETE | `/v1/platform-delegations/{delegation_id}` | `platform:delegate` |
| GET | `/v1/platform/modules` | (sessão válida, sem permissão) |
| GET | `/v1/platform/versions` | (sessão válida, sem permissão) |
| GET | `/v1/roles` | `roles:read` |
| GET | `/v1/team` | `members:read` |
| GET | `/v1/team/activity` | `audit:read` |
| POST | `/v1/team/invites` | `members:manage` |
| DELETE | `/v1/team/invites/{invite_id}` | `members:manage` |
| POST | `/v1/team/invites/{invite_id}/renew` | `members:manage` |
| POST | `/v1/team/members/{user_id}/password-reset` | `members:manage` |
| POST | `/v1/team/members/{user_id}/remove` | `members:manage` |
| GET | `/v1/tenant` | `tenant:read` |
| GET | `/v1/tenant/features` | `tenant:read` |
| GET | `/version` | (pública ou usa credencial no corpo) |
