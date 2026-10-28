# Artefato 2 — Blueprint da Arquitetura Híbrida
## FiberCore AI — Monorepo Structure

## 1. Objetivo

Definir a fundação técnica do monorepo do **FiberCore AI**, alinhado ao PRD Nuclear e ao schema aprovado.

A arquitetura deve permitir:

- MVP rápido sem criar dívida técnica grave.
- Separação clara entre frontend, API, workers, agente e infraestrutura.
- Uso estratégico de Golang em componentes críticos de escala.
- Integração futura com IA sem contaminar o core operacional.
- Escalabilidade por serviços.
- Economia de tokens para agentes de IA/Codex/Cursor, com contextos menores por pasta.

---

## 2. Decisão arquitetural

A arquitetura será **híbrida, modular e orientada a eventos**.

Componentes principais:

- **Frontend:** Next.js / React.
- **API Core:** FastAPI no MVP; alternativa futura em NestJS ou Go.
- **Serviços críticos:** Go.
- **Agente local:** Go.
- **IA/Copiloto:** Python isolado.
- **Banco relacional:** PostgreSQL.
- **Métricas temporais:** TimescaleDB.
- **Event Bus:** NATS no MVP.
- **Cache/Locks:** Redis.
- **Observabilidade:** Prometheus, Grafana, Loki, OpenTelemetry.
- **Infra:** Docker Compose no MVP; Kubernetes na escala.

---

## 3. Visão macro do monorepo

```txt
fibercore-ai/
├── apps/
│   ├── web/                     # Next.js frontend
│   ├── api-core/                # API principal: FastAPI/NestJS/Go
│   ├── ai-copilot/              # Serviço IA/RAG/diagnóstico
│   └── admin-console/           # Futuro: console SaaS interno
│
├── services/
│   ├── agent-gateway/           # Go: comunicação SaaS <-> agentes
│   ├── collector-worker/        # Go: orquestra coletas
│   ├── event-worker/            # Go: processa eventos técnicos
│   ├── correlation-engine/      # Go: cria incidentes por correlação
│   ├── automation-engine/       # Go: dry-run, execução, post-check
│   ├── webhook-dispatcher/      # Go: entrega webhooks
│   └── erp-sync-worker/         # Go ou Python: sincronização ERP
│
├── agents/
│   └── fiber-agent/             # Go: agente local instalado no ISP
│
├── packages/
│   ├── contracts/               # OpenAPI, AsyncAPI, JSON Schema, Protobuf
│   ├── shared-types/            # Tipos comuns gerados
│   ├── ui/                      # Componentes UI compartilhados
│   ├── sdk-js/                  # SDK TypeScript futuro
│   ├── sdk-go/                  # SDK Go interno
│   └── policy/                  # Políticas de automação e permissões
│
├── db/
│   ├── migrations/              # SQL migrations
│   ├── seeds/                   # Dados iniciais
│   ├── fixtures/                # Dados de teste
│   ├── views/                   # Views SQL
│   └── timescale/               # Hypertables, aggregates, retention
│
├── infra/
│   ├── docker/                  # Dockerfiles
│   ├── compose/                 # Docker Compose MVP/dev
│   ├── k8s/                     # Kubernetes futuro
│   ├── helm/                    # Helm charts futuro
│   ├── terraform/               # Infra cloud futuro
│   └── observability/           # Prometheus, Grafana, Loki, OTel
│
├── docs/
│   ├── prd/
│   ├── architecture/
│   │   └── adr/
│   ├── api/
│   ├── runbooks/
│   └── onboarding/
│
├── scripts/
├── tests/
├── .github/workflows/
├── Makefile
├── Taskfile.yml
├── docker-compose.yml
├── .env.example
├── README.md
└── ADR.md
```

---

## 4. apps/web — Frontend Next.js

```txt
apps/web/
├── app/
│   ├── dashboard/
│   ├── olts/
│   ├── onus/
│   ├── customers/
│   ├── incidents/
│   ├── automations/
│   ├── imports/
│   ├── settings/
│   └── login/
├── components/
│   ├── layout/
│   ├── tables/
│   ├── charts/
│   ├── forms/
│   ├── maps/
│   └── domain/
│       ├── olt/
│       ├── onu/
│       ├── customer/
│       ├── incident/
│       └── automation/
├── lib/
│   ├── api-client.ts
│   ├── auth.ts
│   ├── tenant.ts
│   └── formatting.ts
├── hooks/
├── stores/
├── public/
├── tests/
├── package.json
├── next.config.js
└── tsconfig.json
```

Telas MVP:

- Login.
- Dashboard FTTH.
- Cadastro/listagem de OLTs.
- Página da OLT.
- Inventário de ONUs.
- Página ONU 360.
- Importação CSV de clientes.
- Associação ONU x Cliente.
- Alarmes/incidentes básicos.
- Solicitação de reboot autorizado.
- Auditoria básica.

---

## 5. apps/api-core — API principal

Recomendação inicial: **FastAPI**.

```txt
apps/api-core/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── modules/
│   │   ├── auth/
│   │   ├── tenants/
│   │   ├── users/
│   │   ├── roles/
│   │   ├── olts/
│   │   ├── pon_ports/
│   │   ├── onus/
│   │   ├── ctos/
│   │   ├── customers/
│   │   ├── contracts/
│   │   ├── associations/
│   │   ├── incidents/
│   │   ├── alarms/
│   │   ├── automations/
│   │   ├── imports/
│   │   ├── erp_integrations/
│   │   └── audit/
│   ├── db/
│   │   ├── session.py
│   │   ├── models/
│   │   ├── repositories/
│   │   └── migrations_bridge.py
│   ├── services/
│   │   ├── nats_client.py
│   │   ├── audit_service.py
│   │   ├── tenant_context.py
│   │   ├── permission_service.py
│   │   └── idempotency_service.py
│   └── schemas/
├── tests/
├── pyproject.toml
└── Dockerfile
```

Responsabilidades:

- Autenticação.
- Autorização.
- Contexto de tenant.
- Cadastro de OLT.
- Inventário atual.
- Importação CSV.
- Associação ONU x Cliente.
- Solicitação de automações.
- Consulta de auditoria.
- Exposição REST/OpenAPI.
- Publicação de eventos no NATS.
- Consulta de estado atual no PostgreSQL.
- Consulta de métricas agregadas no TimescaleDB.

A API Core **não deve executar diretamente SSH/SNMP/Telnet/comandos em OLT**. Isso deve ser delegado aos serviços Go via Event Bus.

---

## 6. apps/ai-copilot — IA e diagnóstico

```txt
apps/ai-copilot/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── prompts/
│   ├── chains/
│   ├── tools/
│   ├── rag/
│   ├── guardrails/
│   └── modules/
│       ├── incident_summary/
│       ├── customer_diagnosis/
│       ├── noc_daily_report/
│       └── field_checklist/
├── tests/
├── pyproject.toml
└── Dockerfile
```

Responsabilidades:

- Diagnóstico textual.
- Resumo de incidente.
- Checklist para campo.
- Texto para atendimento.
- Análise de risco técnico.
- Consulta controlada ao banco/API.
- RAG sobre runbooks.

Restrições:

- Não executa ação crítica.
- Não acessa secrets.
- Não fala com OLT.
- Não altera estado sem passar pela API Core.

---

## 7. services/agent-gateway — Go

```txt
services/agent-gateway/
├── cmd/agent-gateway/main.go
├── internal/
│   ├── config/
│   ├── auth/
│   ├── websocket/
│   ├── grpc/
│   ├── registry/
│   ├── dispatcher/
│   ├── heartbeat/
│   ├── audit/
│   └── nats/
├── pkg/protocol/
├── tests/
├── go.mod
└── Dockerfile
```

Responsabilidades:

- Receber conexões outbound dos agentes.
- Autenticar agente por token/chave.
- Registrar heartbeat.
- Roteamento de comandos para o agente certo.
- Receber resultados.
- Publicar eventos no NATS.
- Atualizar status do agente.
- Garantir isolamento por tenant.

Comunicação recomendada:

- WebSocket seguro no MVP.
- gRPC streaming em fase posterior.
- mTLS em fase enterprise.

---

## 8. services/collector-worker — Go

```txt
services/collector-worker/
├── cmd/collector-worker/main.go
├── internal/
│   ├── scheduler/
│   ├── planner/
│   ├── rate_limit/
│   ├── nats/
│   ├── repository/
│   ├── normalizer/
│   ├── metrics/
│   └── audit/
├── pkg/
├── tests/
├── go.mod
└── Dockerfile
```

Responsabilidades:

- Agendar coleta por tenant/OLT.
- Respeitar política de coleta.
- Não sobrecarregar OLT.
- Enviar job ao agente.
- Receber snapshot.
- Normalizar payload inicial.
- Atualizar estado atual.
- Gravar métricas TimescaleDB.
- Publicar eventos derivados.

Eventos publicados:

- `olt.status.changed`
- `onu.status.changed`
- `onu.metrics.sampled`
- `pon.mass_down.detected`
- `onu.signal.degraded`
- `connector.agent.offline`

---

## 9. services/event-worker — Go

```txt
services/event-worker/
├── cmd/event-worker/main.go
├── internal/
│   ├── consumers/
│   ├── handlers/
│   ├── state/
│   ├── scoring/
│   ├── repository/
│   ├── nats/
│   └── telemetry/
├── pkg/events/
├── tests/
├── go.mod
└── Dockerfile
```

Responsabilidades:

- Consumir eventos do NATS.
- Atualizar `events`.
- Atualizar estado atual de OLT/PON/ONU.
- Calcular `health_score`.
- Calcular `association_status` derivado.
- Criar/atualizar alarmes simples.
- Publicar eventos enriquecidos para correlação.

---

## 10. services/correlation-engine — Go

```txt
services/correlation-engine/
├── cmd/correlation-engine/main.go
├── internal/
│   ├── rules/
│   ├── windows/
│   ├── aggregators/
│   ├── impact/
│   ├── incident/
│   ├── repository/
│   ├── nats/
│   └── telemetry/
├── pkg/correlation/
├── tests/
├── go.mod
└── Dockerfile
```

Responsabilidades:

- Detectar queda massiva por PON.
- Detectar queda por CTO.
- Detectar OLT crítica.
- Calcular clientes afetados.
- Calcular `affected_revenue`.
- Criar ou atualizar `incidents`.
- Criar `incident_members`.
- Evitar avalanche de alarmes.
- Definir severidade.
- Publicar notificações.

Regras MVP:

- PON massiva: X ONUs offline na mesma PON em Y segundos.
- OLT offline: OLT sem coleta/heartbeat e múltiplas PONs afetadas.
- Cliente ativo offline: contrato ativo + ONU offline.
- ONU sem cliente: ONU online sem associação.
- Cliente suspenso online: contrato suspenso + ONU online.

---

## 11. services/automation-engine — Go

```txt
services/automation-engine/
├── cmd/automation-engine/main.go
├── internal/
│   ├── consumers/
│   ├── policies/
│   ├── validators/
│   ├── dryrun/
│   ├── executor/
│   ├── postcheck/
│   ├── rollback/
│   ├── approvals/
│   ├── repository/
│   ├── nats/
│   └── audit/
├── pkg/automation/
├── tests/
├── go.mod
└── Dockerfile
```

Responsabilidades:

- Consumir solicitações de automação.
- Verificar risco.
- Validar permissão.
- Executar dry-run.
- Aguardar aprovação quando necessário.
- Enviar comando para agente via `agent-gateway`.
- Executar pós-checagem.
- Atualizar `automation_runs`.
- Registrar auditoria.
- Publicar resultado.

Ações MVP:

- Reboot de ONU autorizado.
- Provisionamento básico.
- Associação operacional pós-provisionamento.
- Atualização de descrição da ONU, se habilitada.

---

## 12. services/webhook-dispatcher — Go

```txt
services/webhook-dispatcher/
├── cmd/webhook-dispatcher/main.go
├── internal/
│   ├── consumers/
│   ├── delivery/
│   ├── retry/
│   ├── signing/
│   ├── repository/
│   └── nats/
├── tests/
├── go.mod
└── Dockerfile
```

Responsabilidades:

- Consumir eventos notificáveis.
- Assinar payload.
- Entregar webhook.
- Fazer retry com backoff.
- Registrar falhas.
- Evitar duplicidade com idempotency key.

---

## 13. services/erp-sync-worker

Pode ser Go ou Python.

Recomendação:

- Go para REST simples e alto volume.
- Python para CSV complexo, SOAP legado, transformações pesadas ou integrações mais heterogêneas.

```txt
services/erp-sync-worker/
├── cmd/erp-sync-worker/main.go
├── internal/
│   ├── connectors/
│   │   ├── ixc/
│   │   ├── sgp/
│   │   ├── mk/
│   │   ├── hubsoft/
│   │   └── generic/
│   ├── mapper/
│   ├── sync/
│   ├── repository/
│   ├── nats/
│   └── audit/
├── tests/
├── go.mod
└── Dockerfile
```

---

## 14. agents/fiber-agent — Go

```txt
agents/fiber-agent/
├── cmd/fiber-agent/main.go
├── internal/
│   ├── config/
│   ├── auth/
│   ├── tunnel/
│   ├── heartbeat/
│   ├── queue/
│   ├── executor/
│   ├── collectors/
│   │   ├── huawei/
│   │   ├── zte/
│   │   ├── fiberhome/
│   │   ├── datacom/
│   │   └── generic_snmp/
│   ├── protocols/
│   │   ├── ssh/
│   │   ├── snmp/
│   │   ├── telnet/
│   │   └── httpapi/
│   ├── parsers/
│   ├── normalizer/
│   ├── security/
│   ├── audit/
│   └── updater/
├── pkg/
│   ├── driver/
│   ├── command/
│   └── models/
├── configs/fiber-agent.example.yaml
├── packaging/
│   ├── systemd/
│   ├── docker/
│   └── deb/
├── tests/
├── go.mod
└── Dockerfile
```

Responsabilidades:

- Rodar no ambiente do ISP.
- Abrir conexão outbound com o SaaS.
- Executar comandos read-only por padrão.
- Coletar dados das OLTs.
- Executar comandos aprovados.
- Manter fila local.
- Aplicar timeouts e rate limit por OLT.
- Redigir logs.
- Não armazenar senha em claro.
- Assinar resultados.

Modos:

```txt
read_only
assisted_automation
controlled_autopilot
break_glass
```

Interface de driver sugerida:

```go
type OLTDriver interface {
    CollectOLTStatus(ctx context.Context, target Target) (*OLTStatus, error)
    CollectPONPorts(ctx context.Context, target Target) ([]PONPort, error)
    CollectONUs(ctx context.Context, target Target) ([]ONU, error)
    RebootONU(ctx context.Context, target Target, req RebootONURequest) (*CommandResult, error)
    ProvisionONU(ctx context.Context, target Target, req ProvisionONURequest) (*CommandResult, error)
}
```

---

## 15. packages/contracts

```txt
packages/contracts/
├── openapi/
│   ├── fibercore-v1.yaml
│   └── generated/
├── asyncapi/
│   ├── events-v1.yaml
│   └── generated/
├── jsonschema/
│   ├── olt.schema.json
│   ├── onu.schema.json
│   ├── customer.schema.json
│   ├── automation.schema.json
│   └── event.schema.json
├── protobuf/
│   ├── agent.proto
│   ├── collector.proto
│   └── automation.proto
└── README.md
```

Responsabilidade:

- OpenAPI da API REST.
- AsyncAPI dos eventos.
- JSON Schema dos payloads.
- Protobuf/gRPC futuro.
- Geração de SDKs.
- Evitar contratos espalhados.

---

## 16. db/

```txt
db/
├── migrations/
│   ├── 000001_extensions.sql
│   ├── 000002_enums.sql
│   ├── 000003_base_tenants_users.sql
│   ├── 000004_inventory.sql
│   ├── 000005_customers_contracts.sql
│   ├── 000006_events_incidents.sql
│   ├── 000007_automation_audit.sql
│   ├── 000008_imports.sql
│   └── 000009_timescale_metrics.sql
├── seeds/
├── fixtures/
├── views/
└── timescale/
```

Ferramentas recomendadas:

- SQL puro + Goose, Flyway ou Atlas.
- Evitar ORM como única fonte da verdade para DDL TimescaleDB.

---

## 17. Fluxo de comunicação — Event Bus e Workers Go

### Padrão geral

```txt
Frontend
  ↓ HTTP/REST
API Core
  ↓ publica evento/comando
NATS
  ↓ consumers Go
Workers
  ↓ atualizam banco / publicam novos eventos
PostgreSQL + TimescaleDB
  ↑ consultas
API Core
  ↑ HTTP/REST
Frontend
```

### Por que NATS no MVP

NATS é adequado porque é:

- Simples de operar.
- Leve.
- Rápido.
- Bom para pub/sub.
- Bom para request/reply.
- Natural para serviços Go.

Kafka pode entrar depois se o volume de telemetria justificar.

### Convenção de subjects

```txt
tenant.{tenant_id}.olt.created
tenant.{tenant_id}.olt.collect.requested
tenant.{tenant_id}.olt.collect.completed
tenant.{tenant_id}.olt.status.changed

tenant.{tenant_id}.onu.discovered
tenant.{tenant_id}.onu.status.changed
tenant.{tenant_id}.onu.metrics.sampled
tenant.{tenant_id}.onu.signal.degraded
tenant.{tenant_id}.onu.reboot.requested
tenant.{tenant_id}.onu.reboot.completed

tenant.{tenant_id}.pon.mass_down.detected

tenant.{tenant_id}.customer.import.requested
tenant.{tenant_id}.customer.import.completed
tenant.{tenant_id}.association.completed

tenant.{tenant_id}.incident.created
tenant.{tenant_id}.incident.updated

tenant.{tenant_id}.automation.requested
tenant.{tenant_id}.automation.completed
tenant.{tenant_id}.automation.failed

tenant.{tenant_id}.agent.connected
tenant.{tenant_id}.agent.heartbeat
tenant.{tenant_id}.agent.command.requested
tenant.{tenant_id}.agent.command.completed
```

### Formato padrão de evento

```json
{
  "event_id": "uuid",
  "tenant_id": "uuid",
  "event_type": "onu.status.changed",
  "source": "collector-worker",
  "occurred_at": "2026-06-25T12:00:00Z",
  "correlation_id": "uuid",
  "idempotency_key": "string",
  "entity": {
    "type": "onu",
    "id": "uuid"
  },
  "payload": {},
  "metadata": {}
}
```

---

## 18. Fluxo — Coleta OLT/ONU

```txt
1. API Core cadastra OLT.
2. API Core publica evento olt.created.
3. Collector Worker recebe evento.
4. Collector Worker agenda coleta.
5. Collector Worker envia collect.requested ao Agent Gateway.
6. Agent Gateway envia job ao Fiber Agent.
7. Fiber Agent coleta dados na OLT via SSH/SNMP/API.
8. Fiber Agent retorna snapshot.
9. Agent Gateway publica collect.completed.
10. Collector Worker normaliza snapshot.
11. Collector Worker atualiza olts, pon_ports, onus.
12. Collector Worker grava métricas em TimescaleDB.
13. Collector Worker publica eventos derivados.
14. Event Worker processa eventos.
15. Correlation Engine detecta incidentes.
16. API Core expõe resultado ao frontend.
```

---

## 19. Fluxo — Reboot de ONU autorizado

```txt
1. Usuário solicita reboot no frontend.
2. API Core valida tenant, RBAC e status da ONU.
3. API Core cria automation_run com status requested.
4. API Core calcula risco da ação.
5. Se precisar aprovação, status vira pending_approval.
6. Após aprovação, API Core publica automation.requested.
7. Automation Engine consome evento.
8. Automation Engine executa validações.
9. Automation Engine cria dry-run.
10. Automation Engine envia comando ao Agent Gateway.
11. Agent Gateway envia comando ao Fiber Agent.
12. Fiber Agent executa reboot na OLT.
13. Fiber Agent retorna resultado.
14. Automation Engine executa post-check.
15. Automation Engine atualiza automation_run.
16. Automation Engine registra audit_log.
17. Automation Engine publica automation.completed.
18. Frontend exibe resultado.
```

---

## 20. go.work recomendado

```txt
go 1.23

use (
  ./services/agent-gateway
  ./services/collector-worker
  ./services/event-worker
  ./services/correlation-engine
  ./services/automation-engine
  ./services/webhook-dispatcher
  ./services/erp-sync-worker
  ./agents/fiber-agent
  ./packages/sdk-go
)
```

---

## 21. ADRs iniciais obrigatórios

```txt
docs/architecture/adr/
├── 0001-monorepo-hibrido.md
├── 0002-go-para-servicos-criticos.md
├── 0003-nats-como-event-bus-inicial.md
├── 0004-postgresql-timescaledb.md
├── 0005-agente-local-outbound.md
├── 0006-api-core-fastapi-inicial.md
├── 0007-multi-tenant-por-tenant-id-e-rls.md
├── 0008-automacao-com-governanca.md
└── 0009-ia-isolada-do-core-operacional.md
```

---

## 22. Docker Compose MVP

Serviços mínimos:

```txt
postgres-timescale
redis
nats
api-core
web
agent-gateway
collector-worker
event-worker
correlation-engine
automation-engine
fiber-agent-demo
```

Portas sugeridas:

```txt
web:                 3000
api-core:            8000
ai-copilot:          8010
agent-gateway:       8020
collector-worker:    8030 health
event-worker:        8031 health
correlation-engine:  8032 health
automation-engine:   8033 health
webhook-dispatcher:  8034 health
nats:                4222
nats-monitoring:     8222
postgres-timescale:  5432
redis:               6379
prometheus:          9090
grafana:             3001
```

---

## 23. CI/CD mínimo

```txt
1. Lint frontend
2. Test frontend
3. Build frontend
4. Lint API Core
5. Test API Core
6. Build API Core
7. Go fmt
8. Go vet
9. Go test ./...
10. Build serviços Go
11. Validate SQL migrations
12. Validate OpenAPI
13. Validate AsyncAPI
14. Build Docker images
```

---

## 24. Sequência recomendada de implementação

### Sprint 0 — Fundação

1. Criar monorepo.
2. Criar Docker Compose com Postgres/Timescale, NATS e Redis.
3. Criar migrations do Artefato 1.
4. Criar API Core skeleton.
5. Criar frontend skeleton.
6. Criar agent-gateway skeleton.
7. Criar fiber-agent skeleton.
8. Criar contratos OpenAPI/AsyncAPI iniciais.
9. Criar CI básico.

### Sprint 1 — Cadastro e inventário

1. CRUD Tenant/User básico.
2. CRUD OLT.
3. Agent Gateway conectado.
4. Fiber Agent demo.
5. Collector Worker mock.
6. Inventário de ONUs mock/seed.
7. Tela OLT/ONU.

### Sprint 2 — Coleta real inicial

1. Driver Huawei/ZTE inicial.
2. Coleta de PON.
3. Coleta de ONU.
4. Persistência estado atual.
5. Persistência métrica Timescale.
6. Eventos `onu.status.changed`.

### Sprint 3 — Cliente e associação

1. Importação CSV.
2. Cadastro Customer/Contract.
3. Associação ONU x cliente.
4. Score de associação.
5. View ONU 360.

### Sprint 4 — Alarmes e correlação

1. Event Worker.
2. Alarmes básicos.
3. PON massiva.
4. Incident Members.
5. Dashboard NOC inicial.

### Sprint 5 — Automação segura

1. Automation Run.
2. Reboot ONU autorizado.
3. Dry-run.
4. Post-check.
5. Audit Log.
6. Resultado no frontend.

---

## 25. Decisão final

```txt
Frontend:       Next.js / React
API Core:       FastAPI no MVP; Go/NestJS futuro se necessário
Serviços:       Go
Agente local:   Go
IA:             Python isolado
Banco:          PostgreSQL + TimescaleDB
Event Bus:      NATS no MVP; Kafka somente se volume exigir
Cache/Locks:    Redis
Deploy MVP:     Docker Compose
Deploy escala:  Kubernetes
```
