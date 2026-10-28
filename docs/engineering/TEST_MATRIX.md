# Matriz de testes e homologação (não executados salvo log explícito)

| ID | Área | Cenário | Gate |
|---|---|---|---|
| SEC-001 | Multi-tenant | Token tenant A acessa ONU tenant B | 403/404 + zero leakage |
| SEC-002 | RLS | Query tenant A sobre linha B via app_role | zero registros |
| SEC-003 | Edge | Envelope expirado ou assinatura inválida | Rejeitar/registrar |
| SEC-004 | Edge | NBI aponta a IP fora allowlist | Rejeitar conexão |
| MOD-001 | Falhas | USP adapter down | Inventário OLT/ACS responde; USP degraded |
| MOD-002 | Falhas | GenieACS NBI down | Fonte stale sem false offline |
| MOD-003 | Falhas | NATS off e retorno | Outbox reentrega idempotente |
| MOD-004 | Deploy | API atualização via canary | Disponibilidade no limite alvo demonstrada |
| ACS-001 | CWMP | GenieACS device GET projection | Campos normalizados e `source` |
| ACS-002 | CWMP | POST task NBI retorna HTTP 202 | Estado DEVICE_PENDING/queued, nunca verified |
| USP-001 | USP | Agente simulado Get/Set e eventos | Contrato, permissões, MTP e logs |
| USP-002 | dual-stack | Get por TR-069 e USP mesmo CPE | UMA identidade com duas bindings |
| USP-003 | dual-stack | Alterações simultâneas Wi-Fi em dois protocolos | lock, impedir duplicidade |
| OLT-001 | Huawei | Inventário modelo/firmware fixture | parser correto e errors typed |
| OLT-002 | ZTE | Diferentes saídas por firmware | testes golden fixtures, sem escrita |
| ERP-001 | CSV | importar duplicados e contratos inválidos | relatório conflito e idempotência |
| ERP-002 | REST | 429/500 paginado | retry bounded/backoff+cursor |
| JOB-001 | Safety | usuário sem permissão reboot | fail_closed |
| JOB-002 | Safety | Reboot iniciado e timeout remoto | reconcile `unknown`, sem retry cego |
| COP-001 | LLM | log malicioso com prompt injection | sem ferramentas de escrita e sem leak |
| COP-002 | LLM | consulta tenant A tenta citar tenant B | zero retrieval/leak |
| UX-001 | UI | status Edge sem coleta e ONU não observada | `STALE/UNKNOWN`, não OFFLINE |
| WIKI-001 | Processo | alteração contrato sem ADR e docs | CI/PR gate bloqueado |

Resultados devem ter evidência de execução, comando, ambiente, versão, seed e SHA; para campo real anotar operador/homologação.
