"""Encerrar organização (ADR-0050, fatia E): o PEDIDO pelo operador (com carência) e o registro permanente; a exclusão em si é do dono, pela CLI.

`organization_closures (tenant_id PK SEM FK, name, state, reason, requested_by, requested_at, earliest_close_at, cancelled_at, export_*, closed_at, deleted_rows)`: SEM chave estrangeira e SEM
política por organização, porque precisa sobreviver à exclusão da organização (é o único rastro que fica: nome, motivo, quem pediu, quando, o hash do arquivo exportado e a contagem de linhas
apagadas; nenhum dado de cliente final). A role da aplicação não lê nem escreve a tabela: só as funções abaixo (mesmo contrato da 0054: `SECURITY DEFINER`, dona = dona do esquema,
`search_path` fixo, `platform_assert_actor`, `EXECUTE` só à aplicação).

* `platform_request_organization_closure(p_actor, p_tenant, p_reason, p_request_id)`: só organização **suspensa** e **não demonstração**, uma abertura por vez; carência de 7 dias
  (`earliest_close_at`); grava `platform.closure.requested` na trilha da organização.
* `platform_cancel_organization_closure(p_actor, p_tenant, p_reason, p_request_id)`: cancela um pedido ainda aberto (`platform.closure.cancelled`).
* `platform_closure_state(p_actor, p_tenant)`: o pedido atual da organização (ou nulo) e o histórico dela.
* `platform_list_closures(p_actor)`: o registro permanente (inclusive organizações que já não existem).
A função NÃO apaga nada. Quem apaga é o dono, no host (`org-export` e `org-close`), depois da carência, com o arquivo exportado conferido. Reversível: remove as funções e a tabela.
Revision ID: 0059  Revises: 0058
"""
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

REASON_CHECK = r"""
  IF p_reason IS NULL OR length(p_reason) > 400 THEN RAISE EXCEPTION 'organization_reason_invalid'; END IF;
  rs := regexp_replace(btrim(p_reason), '\s+', ' ', 'g');
  IF length(rs) NOT BETWEEN 3 AND 200 OR rs ~ '[[:cntrl:]]' THEN RAISE EXCEPTION 'organization_reason_invalid'; END IF;
"""
TRAIL = """jsonb_build_object('reason', rs, 'request_id', p_request_id, 'actor_claimed', p_actor, 'session_user', session_user, 'application_name', current_setting('application_name', true))"""

REQUEST = rf"""
CREATE FUNCTION platform_request_organization_closure(p_actor uuid, p_tenant uuid, p_reason text, p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE rs text; prev text; st text; nm text; dm boolean; due timestamptz;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF p_request_id IS NULL THEN RAISE EXCEPTION 'request_id_required'; END IF;
{REASON_CHECK}
  prev := current_setting('app.tenant_id', true);
  PERFORM set_config('app.tenant_id', COALESCE(p_tenant::text, ''), true);
  SELECT t.status, t.name, t.demo INTO st, nm, dm FROM public.tenants t WHERE t.id = p_tenant FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'organization_not_found'; END IF;
  IF dm THEN RAISE EXCEPTION 'organization_is_demo'; END IF;
  IF st <> 'suspended' THEN RAISE EXCEPTION 'organization_not_suspended'; END IF;
  IF EXISTS (SELECT 1 FROM public.organization_closures c WHERE c.tenant_id = p_tenant AND c.state = 'requested') THEN RAISE EXCEPTION 'closure_exists'; END IF;
  due := now() + interval '7 days';
  INSERT INTO public.organization_closures (tenant_id, name, state, reason, requested_by, requested_at, earliest_close_at)
    VALUES (p_tenant, nm, 'requested', rs, p_actor, now(), due)
    ON CONFLICT (tenant_id) DO UPDATE SET state = 'requested', reason = EXCLUDED.reason, requested_by = EXCLUDED.requested_by, requested_at = EXCLUDED.requested_at,
      earliest_close_at = EXCLUDED.earliest_close_at, cancelled_at = NULL, export_at = NULL, export_sha256 = NULL, export_bytes = NULL, export_rows = NULL;
  INSERT INTO public.audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (p_tenant, p_actor, 'platform.closure.requested', 'tenant', p_tenant::text, {TRAIL} || jsonb_build_object('earliest_close_at', due));
  INSERT INTO public.events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
    VALUES (p_tenant, 'tenant', p_tenant, 'platform.closure.requested', '1', jsonb_build_object('by', p_actor));
  PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
  RETURN jsonb_build_object('state', 'requested', 'earliest_close_at', due);
END $$;
"""

CANCEL = rf"""
CREATE FUNCTION platform_cancel_organization_closure(p_actor uuid, p_tenant uuid, p_reason text, p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE rs text; prev text; n integer;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF p_request_id IS NULL THEN RAISE EXCEPTION 'request_id_required'; END IF;
{REASON_CHECK}
  prev := current_setting('app.tenant_id', true);
  PERFORM set_config('app.tenant_id', COALESCE(p_tenant::text, ''), true);
  PERFORM 1 FROM public.tenants t WHERE t.id = p_tenant FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'organization_not_found'; END IF;
  UPDATE public.organization_closures SET state = 'cancelled', cancelled_at = now() WHERE tenant_id = p_tenant AND state = 'requested';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n = 0 THEN RAISE EXCEPTION 'closure_not_found'; END IF;
  INSERT INTO public.audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (p_tenant, p_actor, 'platform.closure.cancelled', 'tenant', p_tenant::text, {TRAIL});
  PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
  RETURN jsonb_build_object('state', 'cancelled');
END $$;
"""

STATE = """
CREATE FUNCTION platform_closure_state(p_actor uuid, p_tenant uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE c record;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  SELECT * INTO c FROM public.organization_closures WHERE tenant_id = p_tenant;
  IF NOT FOUND THEN RETURN jsonb_build_object('closure', NULL); END IF;
  RETURN jsonb_build_object('closure', jsonb_build_object('state', c.state, 'reason', c.reason, 'requested_at', c.requested_at, 'earliest_close_at', c.earliest_close_at,
                            'cancelled_at', c.cancelled_at, 'export_at', c.export_at, 'export_sha256', c.export_sha256, 'export_bytes', c.export_bytes,
                            'ready', c.state = 'requested' AND c.earliest_close_at <= now() AND c.export_sha256 IS NOT NULL));
END $$;
"""

LIST = """
CREATE FUNCTION platform_list_closures(p_actor uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  RETURN jsonb_build_object('items', COALESCE((SELECT jsonb_agg(jsonb_build_object('tenant_id', c.tenant_id, 'name', c.name, 'state', c.state, 'reason', c.reason, 'requested_at', c.requested_at,
                            'earliest_close_at', c.earliest_close_at, 'closed_at', c.closed_at, 'deleted_rows', c.deleted_rows, 'export_sha256', c.export_sha256) ORDER BY c.requested_at DESC)
                            FROM (SELECT * FROM public.organization_closures ORDER BY requested_at DESC LIMIT 200) c), '[]'::jsonb));
END $$;
"""

FUNCS = ["platform_request_organization_closure(uuid, uuid, text, uuid)", "platform_cancel_organization_closure(uuid, uuid, text, uuid)", "platform_closure_state(uuid, uuid)",
         "platform_list_closures(uuid)"]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE organization_closures (
          tenant_id uuid PRIMARY KEY,
          name text NOT NULL,
          state text NOT NULL CHECK (state IN ('requested', 'cancelled', 'closed')),
          reason text NOT NULL CHECK (length(reason) BETWEEN 3 AND 200),
          requested_by uuid,
          requested_at timestamptz NOT NULL,
          earliest_close_at timestamptz NOT NULL,
          cancelled_at timestamptz,
          export_at timestamptz,
          export_sha256 text CHECK (export_sha256 IS NULL OR export_sha256 ~ '^[0-9a-f]{64}$'),
          export_bytes bigint,
          export_rows jsonb,
          closed_at timestamptz,
          closed_by text,
          deleted_rows jsonb
        );
        REVOKE ALL ON organization_closures FROM PUBLIC;
        """
    )
    for sql in (REQUEST, CANCEL, STATE, LIST):
        op.execute(sql)
    op.execute("\n".join(f"REVOKE ALL ON FUNCTION {f} FROM PUBLIC;\nGRANT EXECUTE ON FUNCTION {f} TO fibercore_app;" for f in FUNCS))


def downgrade() -> None:
    for f in FUNCS:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")
    op.execute("DROP TABLE IF EXISTS organization_closures")
