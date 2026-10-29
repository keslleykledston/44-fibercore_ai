# ADR-0023: Adoção incremental da v2.2 e flags por tenant

Status: Accepted (flags por tenant implementadas no PR 36) | Data: 2026-10-29 | Owner: equipe | Origem: adendo v2.2 (DoD, MIGRATION_PLAN)

## Contexto
O DoD v2.2 pede feature flag **por tenant**. Hoje só existe `feature_flag` global por módulo (`configs/modules.yaml`). O repo é monólito modular FastAPI e o adendo proíbe novos deployables sem necessidade provada.

## Decisão
1. **Sem novos containers**: cada capacidade é módulo lógico do core (migração, API, health, testes). 2. Sequência por dependência (FC22-002/003 → 004 → 005/006 → 007/008/009 …), uma fatia vertical por PR (API + DB + teste + manual + capturas + Codex). 3. Migrações só **expand** (tabelas/colunas novas), com backup verificado antes do deploy. 4. Fluxos de escrita permanecem bloqueados; workflows reutilizam o motor de jobs. 5. **Flags por tenant**: tabela mínima `tenant_features(tenant_id, feature, enabled)` introduzida na primeira fatia de **UI nova** (FC22-005); a fatia FC22-002 (leitura que devolve `unknown`) vai sem flag e isso é registrado como **DoD parcial**, não como cumprido.

## Consequências
Rollback por flag/`DROP` de tabela aditiva. Lovable: um pedido em lote no início de FC22-005 (C-14), sem segredos.

**Implementado (PR 36)**: migração 0016 `tenant_features` (RLS forçada, app só lê), catálogo e padrões **no código** (`app/core/features.py`: `capability_registry` ligado por padrão = kill switch; `onu_cpe_links`, `customer_context`, `subscriber_360` desligados), `GET /v1/tenant/features`, CLI `feature-set` (valida nome, evento `tenant.feature.changed`), gate com `403 feature_disabled`. A UI trata 403 omitindo o bloco. DoD de flag por tenant: **cumprido para capacidades novas a partir daqui; FC22-002 passa a ter kill switch**.

