"""Ciclo de vida da organização e console do operador (ADR-0047, fatia A): suspender/reativar, renomear, ligar flags e detalhe com saúde e histórico.

Mesmo contrato da 0053 (`platform_create_organization`): cada função é `SECURITY DEFINER`, DONA = a role dona do esquema, `SET search_path = pg_catalog, public` com tudo de `public`
qualificado, `REVOKE ALL … FROM PUBLIC` e `GRANT EXECUTE` só a `fibercore_app`. Nenhuma confia em contexto de sessão: o ator é PARÂMETRO e `platform_assert_actor` (0053) confere, como dona,
conta ativa + operadora + sessão viva com segundo fator recente (R-3 do ADR-0046, herdado: o banco não prova QUE o operador iniciou a chamada). A role da aplicação continua SEM
`UPDATE` em `tenants` e SEM escrita em `tenant_features`: o único caminho é a função.

* `platform_set_organization_status(p_actor, p_tenant, p_status, p_reason, p_request_id)`: `active|suspended`, motivo obrigatório (3-200, sem controle), idempotente (`changed:false`, sem
  auditoria nova), trava de linha na organização. Grava `platform.organization.suspended|reactivated` na trilha DA organização (de/para, motivo, `request_id`, ator alegado, `session_user`).
* `platform_rename_organization(p_actor, p_tenant, p_name, p_request_id)`: mesmas regras de nome da criação (2-60, único sem diferenciar caixa), na mesma trava consultiva global da criação.
* `platform_set_feature(p_actor, p_tenant, p_feature, p_state, p_reason, p_request_id)`: `on|off|default` (default apaga o override). O catálogo de nomes e as listas "só o dono" vivem no
  CÓDIGO da rota; aqui só o formato. Grava `platform.feature.set` com valor anterior.
* `platform_organization_detail(p_actor, p_tenant)`: estado, saúde (Edges online, OLTs sem coleta), flags com override e o histórico `platform.*` (SÓ chaves de uma lista fixa da evidência; nunca
  dado de cliente final).
* `platform_list_organizations` (substitui a da 0053, mesma assinatura): ganha `edges_online`, `edges_total`, `olts_stale`, `last_heartbeat_at`, `flags_on` (overrides ligados).

Leitura entre provedores com a role dona: uma política SELECT só do dono (`platform_scan`) também em `tenant_features` (como a 0053 fez nas demais). Escritas rodam com o `app.tenant_id` da
organização alvo (a política de escrita de `tenants`/`tenant_features` é por tenant) e o valor anterior é restaurado ao fim.

Limiares da saúde (iguais aos da API): Edge online = heartbeat há no máximo 90 s (`EDGE_OFFLINE_AFTER`); OLT sem coleta = nunca coletada ou última coleta há mais de 60 min (`STALE_AFTER_MIN`).
Reversível: remove as funções e a política; restaura a lista da 0053. Nenhuma coluna nova. Revision ID: 0054  Revises: 0053
"""
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

REASON_CHECK = r"""
  IF p_reason IS NULL OR length(p_reason) > 400 THEN RAISE EXCEPTION 'organization_reason_invalid'; END IF;
  rs := regexp_replace(btrim(p_reason), '\s+', ' ', 'g');
  IF length(rs) NOT BETWEEN 3 AND 200 OR rs ~ '[[:cntrl:]]' THEN RAISE EXCEPTION 'organization_reason_invalid'; END IF;
"""

TRAIL = """jsonb_build_object('reason', rs, 'request_id', p_request_id, 'actor_claimed', p_actor, 'session_user', session_user, 'application_name', current_setting('application_name', true))"""

SET_STATUS = rf"""
CREATE FUNCTION platform_set_organization_status(p_actor uuid, p_tenant uuid, p_status text, p_reason text, p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE rs text; prev text; cur text;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF p_request_id IS NULL THEN RAISE EXCEPTION 'request_id_required'; END IF;
  IF p_status IS NULL OR p_status NOT IN ('active', 'suspended') THEN RAISE EXCEPTION 'organization_status_invalid'; END IF;
{REASON_CHECK}
  prev := current_setting('app.tenant_id', true);
  PERFORM set_config('app.tenant_id', COALESCE(p_tenant::text, ''), true);
  SELECT t.status INTO cur FROM public.tenants t WHERE t.id = p_tenant FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'organization_not_found'; END IF;
  IF cur = p_status THEN
    PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
    RETURN jsonb_build_object('changed', false, 'status', cur);
  END IF;
  UPDATE public.tenants SET status = p_status WHERE id = p_tenant;
  INSERT INTO public.audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (p_tenant, p_actor, CASE WHEN p_status = 'suspended' THEN 'platform.organization.suspended' ELSE 'platform.organization.reactivated' END, 'tenant', p_tenant::text,
            {TRAIL} || jsonb_build_object('from', cur, 'to', p_status));
  INSERT INTO public.events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
    VALUES (p_tenant, 'tenant', p_tenant, 'platform.organization.status_changed', '1', jsonb_build_object('by', p_actor, 'to', p_status));
  PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
  RETURN jsonb_build_object('changed', true, 'status', p_status, 'previous', cur);
END $$;
"""

RENAME = r"""
CREATE FUNCTION platform_rename_organization(p_actor uuid, p_tenant uuid, p_name text, p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE nm text; prev text; cur text;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF p_request_id IS NULL THEN RAISE EXCEPTION 'request_id_required'; END IF;
  IF p_name IS NULL OR length(p_name) > 200 THEN RAISE EXCEPTION 'organization_name_invalid'; END IF;
  nm := regexp_replace(btrim(p_name), '\s+', ' ', 'g');
  IF length(nm) NOT BETWEEN 2 AND 60 OR nm ~ '[[:cntrl:]]' THEN RAISE EXCEPTION 'organization_name_invalid'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('platform-organization-create', 0));   -- the same critical section as the creation: the name check and the write are one
  prev := current_setting('app.tenant_id', true);
  PERFORM set_config('app.tenant_id', COALESCE(p_tenant::text, ''), true);
  SELECT t.name INTO cur FROM public.tenants t WHERE t.id = p_tenant FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'organization_not_found'; END IF;
  IF cur = nm THEN
    PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
    RETURN jsonb_build_object('changed', false, 'name', cur);
  END IF;
  IF EXISTS (SELECT 1 FROM public.tenants t WHERE lower(btrim(t.name)) = lower(nm) AND t.id <> p_tenant) THEN RAISE EXCEPTION 'organization_name_taken'; END IF;
  UPDATE public.tenants SET name = nm WHERE id = p_tenant;
  INSERT INTO public.audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (p_tenant, p_actor, 'platform.organization.renamed', 'tenant', p_tenant::text,
            jsonb_build_object('from', cur, 'to', nm, 'request_id', p_request_id, 'actor_claimed', p_actor, 'session_user', session_user,
                               'application_name', current_setting('application_name', true)));
  INSERT INTO public.events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
    VALUES (p_tenant, 'tenant', p_tenant, 'platform.organization.renamed', '1', jsonb_build_object('by', p_actor));
  PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
  RETURN jsonb_build_object('changed', true, 'name', nm, 'previous', cur);
END $$;
"""

OWNER_ONLY = ("bench_writes", "smart_diagnostics_active_tests", "smart_diagnostics_remediation", "quality_active_tests", "smart_diagnostics_copilot")
OWNER_ONLY_SQL = ", ".join(f"'{f}'" for f in OWNER_ONLY)

SET_FEATURE = rf"""
CREATE FUNCTION platform_set_feature(p_actor uuid, p_tenant uuid, p_feature text, p_state text, p_reason text, p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE rs text; prev text; had boolean; was boolean; before_s text; after_s text;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF p_request_id IS NULL THEN RAISE EXCEPTION 'request_id_required'; END IF;
  IF p_feature IS NULL OR p_feature !~ '^[a-z][a-z0-9_]{{1,63}}$' THEN RAISE EXCEPTION 'feature_invalid'; END IF;   -- the catalog of names lives in the route; only the shape is checked here
  IF p_state IS NULL OR p_state NOT IN ('on', 'off', 'default') THEN RAISE EXCEPTION 'feature_state_invalid'; END IF;
  -- the flags that WRITE to the network or hand decisions to an AI are never turned ON from here, whoever calls (Codex r1, HIGH): the owner's CLI is the only way. Keep in step with
  -- OWNER_ONLY_FEATURES in app/api/platform_orgs.py (a test compares the two lists)
  IF p_state = 'on' AND p_feature IN ({OWNER_ONLY_SQL}) THEN RAISE EXCEPTION 'owner_only_feature'; END IF;
{REASON_CHECK}
  prev := current_setting('app.tenant_id', true);
  PERFORM set_config('app.tenant_id', COALESCE(p_tenant::text, ''), true);
  PERFORM 1 FROM public.tenants t WHERE t.id = p_tenant FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'organization_not_found'; END IF;
  SELECT f.enabled INTO was FROM public.tenant_features f WHERE f.tenant_id = p_tenant AND f.feature = p_feature FOR UPDATE;
  had := FOUND;
  before_s := CASE WHEN NOT had THEN 'default' WHEN was THEN 'on' ELSE 'off' END;
  after_s := p_state;
  IF before_s = after_s THEN
    PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
    RETURN jsonb_build_object('changed', false, 'state', before_s);
  END IF;
  IF p_state = 'default' THEN
    DELETE FROM public.tenant_features WHERE tenant_id = p_tenant AND feature = p_feature;
  ELSE
    INSERT INTO public.tenant_features (tenant_id, feature, enabled) VALUES (p_tenant, p_feature, p_state = 'on')
      ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now();
  END IF;
  INSERT INTO public.audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (p_tenant, p_actor, 'platform.feature.set', 'tenant', p_tenant::text,
            {TRAIL} || jsonb_build_object('feature', p_feature, 'from', before_s, 'to', after_s));
  PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
  RETURN jsonb_build_object('changed', true, 'state', after_s, 'previous', before_s);
END $$;
"""

HEALTH = """
      'edges', (SELECT count(*) FROM public.edges e WHERE e.tenant_id = t.id AND e.status <> 'revoked'),
      'edges_total', (SELECT count(*) FROM public.edges e WHERE e.tenant_id = t.id AND e.status <> 'revoked'),
      'edges_online', (SELECT count(*) FROM public.edges e WHERE e.tenant_id = t.id AND e.status <> 'revoked' AND e.last_heartbeat_at IS NOT NULL
                                AND e.last_heartbeat_at > clock_timestamp() - interval '90 seconds'),
      'last_heartbeat_at', (SELECT max(e.last_heartbeat_at) FROM public.edges e WHERE e.tenant_id = t.id AND e.status <> 'revoked'),
      'olts', (SELECT count(*) FROM public.olts l WHERE l.tenant_id = t.id),
      'olts_stale', (SELECT count(*) FROM public.olts l JOIN public.edges e ON e.tenant_id = l.tenant_id AND e.id = l.edge_id
                      WHERE l.tenant_id = t.id AND e.status <> 'revoked' AND (l.observed_at IS NULL OR l.observed_at < clock_timestamp() - interval '60 minutes')),
      'onus', (SELECT count(*) FROM public.onus n WHERE n.tenant_id = t.id),
      'flags_on', (SELECT count(*) FROM public.tenant_features f WHERE f.tenant_id = t.id AND f.enabled),
"""

DETAIL = rf"""
CREATE FUNCTION platform_organization_detail(p_actor uuid, p_tenant uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE out jsonb;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  SELECT jsonb_build_object(
      'tenant_id', t.id, 'name', t.name, 'status', t.status, 'created_at', t.created_at,{HEALTH}
      'features', (SELECT COALESCE(jsonb_agg(jsonb_build_object('feature', f.feature, 'enabled', f.enabled, 'updated_at', f.updated_at) ORDER BY f.feature), '[]'::jsonb)
                     FROM public.tenant_features f WHERE f.tenant_id = t.id),
      'history', (SELECT COALESCE(jsonb_agg(h ORDER BY h_at DESC), '[]'::jsonb) FROM (
                    SELECT a.created_at AS h_at, jsonb_build_object(
                      'at', a.created_at, 'action', a.action, 'actor', u.display_name,
                      'detail', jsonb_strip_nulls(jsonb_build_object('reason', a.evidence_redacted -> 'reason', 'from', a.evidence_redacted -> 'from', 'to', a.evidence_redacted -> 'to',
                                                                   'feature', a.evidence_redacted -> 'feature', 'name', a.evidence_redacted -> 'name'))) AS h
                      FROM public.audit_log a LEFT JOIN public.users_global u ON u.id = a.actor_id
                     WHERE a.tenant_id = t.id AND a.action IN ('platform.organization.created', 'platform.organization.suspended', 'platform.organization.reactivated',
                                                               'platform.organization.renamed', 'platform.feature.set')
                     ORDER BY a.created_at DESC LIMIT 50) x)
    ) INTO out
    FROM public.tenants t WHERE t.id = p_tenant;
  IF out IS NULL THEN RAISE EXCEPTION 'organization_not_found'; END IF;
  RETURN out;
END $$;
"""

# the 0053 list with the health keys; `edges`, `olts` and `onus` keep their names (the screen and the tests already read them)
LIST_OLD_HEALTH = """
      'edges', (SELECT count(*) FROM public.edges e WHERE e.tenant_id = t.id AND e.status <> 'revoked'),
      'olts', (SELECT count(*) FROM public.olts l WHERE l.tenant_id = t.id),
      'onus', (SELECT count(*) FROM public.onus n WHERE n.tenant_id = t.id),
"""

LIST_SQL = r"""
CREATE OR REPLACE FUNCTION platform_list_organizations(p_actor uuid, p_before_at timestamptz DEFAULT NULL, p_before_id uuid DEFAULT NULL, p_limit integer DEFAULT 100) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE lim integer := LEAST(GREATEST(COALESCE(p_limit, 100), 1), 200); out jsonb; total bigint; more boolean; last_at timestamptz; last_id uuid;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF (p_before_at IS NULL) <> (p_before_id IS NULL) THEN RAISE EXCEPTION 'organization_cursor_invalid'; END IF;
  SELECT count(*) INTO total FROM public.tenants;
  WITH page AS (
    SELECT t.id, t.created_at, jsonb_build_object(
      'tenant_id', t.id, 'name', t.name, 'status', t.status, 'created_at', t.created_at,@@HEALTH@@
      'created_by_name', (SELECT u.display_name FROM public.audit_log a JOIN public.users_global u ON u.id = a.actor_id
                           WHERE a.tenant_id = t.id AND a.action = 'platform.organization.created' LIMIT 1),
      'created_via', CASE WHEN EXISTS (SELECT 1 FROM public.audit_log a WHERE a.tenant_id = t.id AND a.action = 'platform.organization.created') THEN 'screen' ELSE 'cli' END,
      'api_trail', CASE WHEN EXISTS (SELECT 1 FROM public.audit_log a WHERE a.tenant_id = t.id AND a.action = 'platform.organization.created')
                        THEN EXISTS (SELECT 1 FROM public.audit_log c WHERE c.tenant_id = t.id AND c.action = 'platform.organization.created'
                                      AND EXISTS (SELECT 1 FROM public.audit_log r WHERE r.tenant_id = t.id AND r.action = 'platform.organization.requested'
                                                   AND r.evidence_redacted ->> 'request_id' = c.evidence_redacted ->> 'request_id')) END,
      'invite_state', (SELECT CASE WHEN i.accepted_at IS NOT NULL THEN 'accepted' WHEN i.revoked_at IS NOT NULL THEN 'revoked'
                                   WHEN i.expires_at <= now() THEN 'expired' ELSE 'pending' END
                         FROM public.member_invites i WHERE i.tenant_id = t.id AND i.platform_origin ORDER BY i.created_at DESC LIMIT 1)
    ) AS o
    FROM public.tenants t
    WHERE p_before_at IS NULL OR (t.created_at, t.id) < (p_before_at, p_before_id)
    ORDER BY t.created_at DESC, t.id DESC LIMIT lim + 1
  ), shown AS (SELECT * FROM page ORDER BY created_at DESC, id DESC LIMIT lim)
  SELECT COALESCE((SELECT jsonb_agg(o ORDER BY created_at DESC, id DESC) FROM shown), '[]'::jsonb), (SELECT count(*) > lim FROM page),
         (SELECT created_at FROM shown ORDER BY created_at ASC, id ASC LIMIT 1), (SELECT id FROM shown ORDER BY created_at ASC, id ASC LIMIT 1)
    INTO out, more, last_at, last_id;
  RETURN jsonb_build_object('total', total, 'items', out, 'next', CASE WHEN more THEN jsonb_build_object('before_at', last_at, 'before_id', last_id) END);
END $$;
"""

FUNCS = (
    "platform_set_organization_status(uuid, uuid, text, text, uuid)",
    "platform_rename_organization(uuid, uuid, text, uuid)",
    "platform_set_feature(uuid, uuid, text, text, text, uuid)",
    "platform_organization_detail(uuid, uuid)",
)


def upgrade() -> None:
    op.execute("DO $$ BEGIN EXECUTE format($p$CREATE POLICY platform_scan ON tenant_features FOR SELECT TO %I USING (true)$p$, current_user); END $$;")
    op.execute(SET_STATUS)
    op.execute(RENAME)
    op.execute(SET_FEATURE)
    op.execute(DETAIL)
    op.execute(LIST_SQL.replace("@@HEALTH@@", HEALTH))
    revokes = "\n".join(f"REVOKE ALL ON FUNCTION {f} FROM PUBLIC;\nGRANT EXECUTE ON FUNCTION {f} TO fibercore_app;" for f in FUNCS)
    op.execute(revokes)


def downgrade() -> None:
    op.execute(LIST_SQL.replace("@@HEALTH@@", LIST_OLD_HEALTH))
    for f in FUNCS:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")
    op.execute("DROP POLICY IF EXISTS platform_scan ON tenant_features")
