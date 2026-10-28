# Contrato operacional de módulo

Cada módulo em `configs/modules.yaml` deve declarar:

- `id`, `version`, `kind` (core/optional/edge/external), `owner`, `image`, `feature_flag`;
- `requires` (dependências críticas), `optional_dependencies` (degradam mas não bloqueiam), `capabilities`;
- `exposes` rotas REST, eventos versionados, métricas, `/livez`, `/readyz`, `/metrics`, `GET /version`;
- `startup_probe`, `healthcheck`, `timeouts`, `retry_budget`, `circuit_breaker`, `resource_limits`, `security_context`;
- `migrations` com estratégia expand/contract; `failure_mode`, `fallback`, `rollback` e `data_owner`.

## Estados operacionais

`disabled`: não instalado/flag off; `starting`: bootstrap; `healthy`: pronto; `degraded`: dependência opcional ausente ou latência; `unhealthy`: falha que afeta capacidades anunciadas; `maintenance`: janela; `unknown`: falta de heartbeat. Mudanças registradas via estado e relógio monotônico; não bloquear boot do Core por conectores opcionais.

## Supervisão

- Fleet registry: versão, agent/build, último heartbeat, capacidade, autenticação, lag, saúde observada e prontidão.
- Painel de módulos: origem, dependências afetadas, falhas recentes, métricas, botão `retry` de job seguro; ações de restart/deploy restritas ao control plane e não colocadas diretamente no UI sem Gate.
- Falha > limiar: circuit breaker; fallback de leitura/cache (marcado stale); abrir incidente infra; **não** autorreiniciar indefinidamente workflows de escrita.
- Tasks: `job_id`, `tenant_id`, `target_id`, `operation`, `intent_hash`, `idempotency_key`, `expires_at`, `risk`, `policy_version`, `approval_ids`, `state`, `external_task_id`, `before/after` redigidos e provas de verificação.
- Mensagens: `envelope_id`, `schema_version`, `tenant_id`, `correlation_id`, `causation_id`, `timestamp`, `ttl`, `payload_digest`, assinatura/mTLS.

## Contrato adapter (tr069/tr369/olt/erp)

`discover`, `get_capabilities`, `read_fields`, `watch_events`, `prepare_action`, `execute_action`, `get_action_status`, `verify_action`, `abort_if_supported`; cada método aceita contexto de tenant/target, deadline, correlation e origem e retorna erro tipado (`UNSUPPORTED`, `STALE`, `PERMISSION`, `CONFLICT`, `TIMEOUT`, `REQUIRES_APPROVAL`, `TRANSIENT`, `FATAL`). Plugins não recebem credenciais globais nem conexão SQL ao schema de outros domínios.

## Políticas de compatibilidade

- Se versão major do adapter difere, bloquear recurso afetado (não plataforma inteira).
- Novas operações somente com capability `certified` e feature flag por tenant/canary.
- É proibido instalar plugins arbitrários executáveis vindos de tenants. Catálogo de drivers assinado/revisado, bundles imutáveis, SBOM e testes de supply chain.

## Módulo lógico Help Center

`help-center` será integrado no runtime `web`, **não requer container isolado**. Expor liveness do frontend e teste sintético da rota `/ajuda`; falha de conteúdo de ajuda não derruba o inventário ou módulos de rede. Somente publicar artigos com status `published`, screenshots reais e versão revisada. Documentação interna permanece inacessível pelo público.
