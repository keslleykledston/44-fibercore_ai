# Integração de dados e API no repositório

## Rotas
- `contracts/olt-provisioning-v2.5.openapi.yaml`: discovery, profile inventory, service templates, preview de autorização, approval e jobs.
- `contracts/expert-profile-v2.5.1.openapi.yaml`: snapshot read-only, import, clone draft, GET/PATCH ETag, compare, preview por OLT e request de publicação.
- Ambas declaram `/api/v1` no proxy, são **propostas aditivas**. Não duplicar `Approval` ou `Jobs` do projeto; ajustar paths existentes e versionamento via ADR antes de implementar. Não expor endpoint de SSH/CLI livre.

## Tabelas propostas (nomes podem adaptar o projeto)
- `olt_onu_discovery_observations(tenant_id, olt_id, pon_locator, serial, observed_at, freshness, source, evidence_hash)`
- `service_intent_templates(tenant_id, template_id, version, status, canonical_json, hash, created_by)`
- `olt_native_profile_snapshots(tenant_id, olt_id, native_kind, native_id, fw, card, observed_at, completeness, fingerprint, reference_count NULLABLE, normalized_json, unknown_fields)`
- `profile_expert_drafts(tenant_id, draft_id, etag, base_source_hash, desired_json, editor_id, reason, updated_at)`
- `profile_expert_patch_log(tenant_id, draft_id, revision, actor, json_patch_sanitized, reason, created_at)`
- `olt_profile_bindings(tenant_id, olt_id, template_version_id, native_profile_kind, local_native_id, strategy, source_fingerprint, status)`
- `olt_provisioning_plans(tenant_id, plan_id, plan_hash, target_olt_id, preconditions, risk, expires_at, approval_id, state)`
- `olt_provisioning_jobs(tenant_id, job_id, plan_id, idempotency_key, state, retry_policy, postcheck_evidence)`

Todos os IDs referenciados devem ser tenant-scoped e RLS, com unicidade local por OLT e tipo. Armazenar snapshots como dados não confiáveis sanitizados; snapshots e templates publicados imutáveis. Considerar retenção auditável.

## Regras de endpoints
- `GET` é read-only. Import não altera OLT.
- `PATCH` exige `If-Match`; `409` ou `412` em revisão concorrente; `422` campo inválido/unsupported.
- `preview` retorna dados por alvo e `plan_hash`; nunca faz writes. IDs reservados só sob lock na fase de prepare.
- Publicar template = catálogo, não distribuição ao equipamento. Deploy passa pelo executor único.
- `execute` retorna job `QUEUED`, não sucesso de serviço. SSE/poll do job para observabilidade.
- Segredos de OLT/HubSoft residem em vault/secret store no Edge conforme arquitetura; não no browser e não em logs/fixtures.
