# SRE, Docker e orquestração confiável

## Separar dois tipos de orquestração

**Infraestrutura:** Docker Compose controla desenvolvimento e piloto single-host; K3s/Kubernetes controla rescheduling, rolling updates e réplicas no ambiente HA. **Negócio:** `automation-jobs` usa outbox + NATS JetStream + máquina de estados no PostgreSQL; engine de workflow longa duração (Temporal) é ADR futura se necessário. Nunca delegar aprovações de engenharia ao orquestrador de containers.

## Ambiente

- **Dev:** Compose no notebook/VM. API e Edge simulator, PostgreSQL, NATS (JetStream com volume), Prometheus opcional.
- **Staging:** ambiente separado, dados sintéticos/redigidos, GenieACS lab e USP Agent simulado; CI gera builds imutáveis e migration-check.
- **Piloto real:** Edge instalado no site, NBI preexistente privado; inventário em read-only inicialmente; sem abrir CWMP para Cloud; backup offhost verificado.
- **Prod HA:** K3s/Kubernetes com >=2 réplicas stateless, nodes separados, PostgreSQL com failover externo e backups, JetStream cluster e estratégia de partição Edge.

## Probes e supervisão

- `/livez`: processo aceita requisição, sem testar indiscriminadamente dependências remotas (evita restart storms).
- `/readyz`: pronto para tráfego crítico (schema/auth/DB); conectores externos opcionais reportam `degraded` e não forçam desligar o core.
- `/metrics`: requests, `module_health`, `edge_last_heartbeat_seconds`, `nats_consumer_lag`, `outbox_pending`, `job_age_seconds`, `failed_job_count`, `cpe_task_queued_age`, `poll_latency`, `collect_success_rate`, `stale_entities`, `db_pool_utilization`, `release_canary_errors`.
- SLI e alertas: Edge sem heartbeat >90 s (proposta configurável), NBI timeout, backlog > threshold por tenant, DLQ >0, taxa de reboot falho, auth 5xx, latência API p95; sem limiares fixos não homologados em dispositivos.
- Docker restart policy reinicia processo finalizado; **healthcheck falhando não garante restart automático de container unhealthy**. Evitar watchdog root com Docker socket. Compose `depends_on: service_healthy` apenas governa inicialização; não assegura HA.

## Lifecycle de módulo

`REGISTERED -> STARTING -> HEALTHY` ou `DEGRADED` -> `UNHEALTHY` -> `RECOVERING`/`DISABLED`. O módulo anuncia capacidades reais; flags permitem desligar apenas integração defeituosa. Falha do `usp-tr369` não derruba `acs-cwmp` ou inventário.

## Estratégia de release

1. Gerar release imutável com SBOM, imagem por digest, scan e assinatura; validar `semver` API/module/event contracts.
2. Executar tests unit/integration/smoke e migration dry-run no staging.
3. Expand migration idempotente; criar backup e validar restore em staging; app anterior deve continuar compatível durante rollout.
4. Deploy `canary` em % controlado de tenants/agentes, monitorar SLO/erros/DLQ durante janela de observação.
5. Se métricas ruins, **parar rollout**, desabilitar feature flag, reverter imagem/serviço quando seguro; se schema/firmware irreversível, seguir procedimento de compensação, não executar down migration insegura.
6. Promover release; atualizar changelog, wiki, compatibility matrix e relatório do Codex.

## Política de jobs

- Persistir jobs e intenção antes de enfileirar via outbox transacional.
- Pelo menos uma entrega é possível; usar dedupe por `idempotency_key` e fencing tokens para impedir concorrência.
- Operações de leitura são reexecutáveis; escritas não idempotentes devem reconciliar resultado externo antes de novo disparo.
- `queued` no GenieACS 202 não é sucesso. Expirar job e marcar `unknown` sob perda de confirmação, nunca assumir êxito.
- Recovery Edge: fila local SQLite WAL criptografada quando possível, operação limitada por TTL, backoff com jitter, replay idempotente e proteção contra replay de jobs expirados.

## Falhas obrigatórias a injetar

1. Derrubar container opcional USP; core e ACS continuam servindo, UI avisa degradado.
2. Derrubar API; restaurar; jobs de comando não duplicam e resultados retornam.
3. Perder Edge por 20 min; jobs expiram e telemetria mostra `stale`.
4. Perder NBI; coletor exibe motivo, não marca CPE offline indiscriminadamente.
5. NATS indisponível; outbox preserva eventos e worker retoma sem perda/deduplicados.
6. Reiniciar PostgreSQL; conexões retentam, readiness retorna unhealthy e recupera depois.
7. Deploy versão incompatível do driver; capability correspondente é desabilitada por version gate.
8. Duas escritas concorrentes de Wi-Fi (CWMP/USP); uma é negada via lock por alvo e escopo.

## Backup e DR

PostgreSQL PITR/WAL + backup externo testado, NATS stream snapshots conforme retenção, edge local state recuperável; credenciais geridas via secret store (nunca backup em plaintext); restore runbook com RPO/RTO alvo a definir por contrato e validar em exercícios mensais. Queda de host Compose não tem failover automático. Não declarar 99,9% sem medição.

## Serviços do bootstrap

`postgres`, `nats`, `api-core`; `prometheus` em profile `observability`; agentes reais e GenieACS **não** são instalados ou substituídos no compose de núcleo. Serviços futuros `web`, `edge-gateway`, `worker`, `catalog`, `usp-controller-adapter`, `copilot` só recebem profiles quando houver implementação e testes reais.

## Hostname frontend e SLO de publicação

Publicar somente em `https://fibercore.devops.k3gsolutions.com.br` após aprovação. Monitorar status/latência HTTP no ingress, validade de certificado, erros 4xx/5xx, redirect HTTP->HTTPS, rotas `/ajuda` e `/api/v1`. Alertar separadamente indisponibilidade de frontend, API e módulo opcional. Rollbacks não podem apagar documentação nem invalidar URLs de ajuda; manter `help_slug` estável ou redirects versionados.
