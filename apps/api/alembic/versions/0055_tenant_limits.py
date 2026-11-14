"""Limites técnicos por organização (ADR-0047, fatia B): tabela `tenant_limits` e as duas funções do operador. Sem plano, sem preço, sem medição para cobrança (D0).

`tenant_limits (tenant_id PK, max_edges, max_olts, max_members, ingest_per_minute, ingest_burst, updated_by, updated_at)`. Uma coluna NULL = "usar o padrão do código"
(`app/core/limits.py` + `Settings`): a linha só existe quando o operador mudou algo. A role da aplicação só LÊ (política por organização, mais a `platform_scan` do dono, como a 0054 fez em
`tenant_features`); o único caminho de escrita é a função.

* `platform_set_limits(p_actor, p_tenant, p_limits jsonb, p_reason, p_request_id)`: mesmas garantias da 0054 (`SECURITY DEFINER`, dona = dona do esquema, `search_path` fixo,
  `platform_assert_actor`, motivo 3-200, `request_id`, `EXECUTE` só à aplicação). `p_limits` é um objeto com chaves de uma lista fixa; valor número = define, `null` = volta ao padrão, chave
  ausente = não mexe. Faixas validadas aqui (o banco é a última palavra). Idempotente (`changed:false`). Grava `platform.limits.set` (de/para) na trilha da organização.
* `platform_organization_limits(p_actor, p_tenant)`: o que está definido, o uso atual (Edges não revogados, OLTs, membros e convites abertos) e o histórico `platform.limits.set`. O padrão do código é somado pela rota.

O limite NUNCA apaga nem bloqueia o que já existe: quem impõe é a API, na hora de CRIAR (`app/core/limits.py`). Reversível: remove as funções, a política e a tabela. Revision ID: 0055  Revises: 0054
"""
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

KEYS = {"max_edges": (0, 10000), "max_olts": (0, 100000), "max_members": (0, 10000), "ingest_per_minute": (1, 60000), "ingest_burst": (1, 10000)}
KEYS_SQL = ", ".join(f"'{k}'" for k in KEYS)

REASON_CHECK = r"""
  IF p_reason IS NULL OR length(p_reason) > 400 THEN RAISE EXCEPTION 'organization_reason_invalid'; END IF;
  rs := regexp_replace(btrim(p_reason), '\s+', ' ', 'g');
  IF length(rs) NOT BETWEEN 3 AND 200 OR rs ~ '[[:cntrl:]]' THEN RAISE EXCEPTION 'organization_reason_invalid'; END IF;
"""

TRAIL = """jsonb_build_object('reason', rs, 'request_id', p_request_id, 'actor_claimed', p_actor, 'session_user', session_user, 'application_name', current_setting('application_name', true))"""

RANGE_CHECKS = "\n".join(
    f"""    IF p_limits ? '{k}' AND jsonb_typeof(p_limits -> '{k}') <> 'null' AND (jsonb_typeof(p_limits -> '{k}') <> 'number' OR (p_limits ->> '{k}') !~ '^[0-9]+$'
       OR (p_limits ->> '{k}')::numeric NOT BETWEEN {lo} AND {hi}) THEN RAISE EXCEPTION 'limits_invalid'; END IF;"""
    for k, (lo, hi) in KEYS.items()
)

SET_LIMITS = rf"""
CREATE FUNCTION platform_set_limits(p_actor uuid, p_tenant uuid, p_limits jsonb, p_reason text, p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE rs text; prev text; k text; cur jsonb; nxt jsonb; had boolean;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF p_request_id IS NULL THEN RAISE EXCEPTION 'request_id_required'; END IF;
  IF p_limits IS NULL OR jsonb_typeof(p_limits) <> 'object' OR p_limits = '{{}}'::jsonb THEN RAISE EXCEPTION 'limits_invalid'; END IF;
  FOR k IN SELECT jsonb_object_keys(p_limits) LOOP
    IF k NOT IN ({KEYS_SQL}) THEN RAISE EXCEPTION 'limits_invalid'; END IF;
  END LOOP;
{RANGE_CHECKS}
{REASON_CHECK}
  prev := current_setting('app.tenant_id', true);
  PERFORM set_config('app.tenant_id', COALESCE(p_tenant::text, ''), true);
  PERFORM 1 FROM public.tenants t WHERE t.id = p_tenant FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'organization_not_found'; END IF;
  SELECT to_jsonb(l) - 'tenant_id' - 'updated_by' - 'updated_at' INTO cur FROM public.tenant_limits l WHERE l.tenant_id = p_tenant FOR UPDATE;
  had := FOUND;
  IF NOT had THEN cur := jsonb_build_object('max_edges', NULL, 'max_olts', NULL, 'max_members', NULL, 'ingest_per_minute', NULL, 'ingest_burst', NULL); END IF;
  nxt := cur || p_limits;
  IF nxt = cur THEN
    PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
    RETURN jsonb_build_object('changed', false, 'limits', cur);
  END IF;
  INSERT INTO public.tenant_limits (tenant_id, max_edges, max_olts, max_members, ingest_per_minute, ingest_burst, updated_by, updated_at)
    VALUES (p_tenant, (nxt ->> 'max_edges')::int, (nxt ->> 'max_olts')::int, (nxt ->> 'max_members')::int, (nxt ->> 'ingest_per_minute')::int, (nxt ->> 'ingest_burst')::int, p_actor, now())
    ON CONFLICT (tenant_id) DO UPDATE SET max_edges = EXCLUDED.max_edges, max_olts = EXCLUDED.max_olts, max_members = EXCLUDED.max_members,
      ingest_per_minute = EXCLUDED.ingest_per_minute, ingest_burst = EXCLUDED.ingest_burst, updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at;
  INSERT INTO public.audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (p_tenant, p_actor, 'platform.limits.set', 'tenant', p_tenant::text, {TRAIL} || jsonb_build_object('from', cur, 'to', nxt));
  PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
  RETURN jsonb_build_object('changed', true, 'limits', nxt, 'previous', cur);
END $$;
"""

READ_LIMITS = """
CREATE FUNCTION platform_organization_limits(p_actor uuid, p_tenant uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE out jsonb;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  SELECT jsonb_build_object(
      'limits', COALESCE((SELECT to_jsonb(l) - 'tenant_id' - 'updated_by' FROM public.tenant_limits l WHERE l.tenant_id = t.id),
                         jsonb_build_object('max_edges', NULL, 'max_olts', NULL, 'max_members', NULL, 'ingest_per_minute', NULL, 'ingest_burst', NULL, 'updated_at', NULL)),
      'usage', jsonb_build_object(
        'edges', (SELECT count(*) FROM public.edges e WHERE e.tenant_id = t.id AND e.status <> 'revoked'),
        'olts', (SELECT count(*) FROM public.olts l WHERE l.tenant_id = t.id),
        'members', (SELECT count(*) FROM public.tenant_memberships m WHERE m.tenant_id = t.id),
        'invites_open', (SELECT count(*) FROM public.member_invites i WHERE i.tenant_id = t.id AND i.purpose = 'invite' AND i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now())),
      'history', (SELECT COALESCE(jsonb_agg(h ORDER BY h_at DESC), '[]'::jsonb) FROM (
                    SELECT a.created_at AS h_at, jsonb_build_object(
                      'at', a.created_at, 'action', a.action, 'actor', u.display_name,
                      'detail', jsonb_strip_nulls(jsonb_build_object('reason', a.evidence_redacted -> 'reason', 'from', a.evidence_redacted -> 'from', 'to', a.evidence_redacted -> 'to'))) AS h
                      FROM public.audit_log a LEFT JOIN public.users_global u ON u.id = a.actor_id
                     WHERE a.tenant_id = t.id AND a.action = 'platform.limits.set'
                     ORDER BY a.created_at DESC LIMIT 30) x)
    ) INTO out
    FROM public.tenants t WHERE t.id = p_tenant;
  IF out IS NULL THEN RAISE EXCEPTION 'organization_not_found'; END IF;
  RETURN out;
END $$;
"""

FUNCS = ["platform_set_limits(uuid, uuid, jsonb, text, uuid)", "platform_organization_limits(uuid, uuid)"]


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE tenant_limits (
          tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
          max_edges integer CHECK (max_edges BETWEEN 0 AND 10000),
          max_olts integer CHECK (max_olts BETWEEN 0 AND 100000),
          max_members integer CHECK (max_members BETWEEN 0 AND 10000),
          ingest_per_minute integer CHECK (ingest_per_minute BETWEEN 1 AND 60000),
          ingest_burst integer CHECK (ingest_burst BETWEEN 1 AND 10000),
          updated_by uuid REFERENCES users_global(id),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE tenant_limits ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_limits FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tenant_limits USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON tenant_limits TO fibercore_app;
        """
    )
    op.execute("DO $$ BEGIN EXECUTE format($p$CREATE POLICY platform_scan ON tenant_limits FOR SELECT TO %I USING (true)$p$, current_user); END $$;")
    op.execute(SET_LIMITS)
    op.execute(READ_LIMITS)
    op.execute("\n".join(f"REVOKE ALL ON FUNCTION {f} FROM PUBLIC;\nGRANT EXECUTE ON FUNCTION {f} TO fibercore_app;" for f in FUNCS))


def downgrade() -> None:
    for f in FUNCS:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")
    op.execute("DROP TABLE IF EXISTS tenant_limits")
