"""Escopo por site/OLT (ADR-0049 D2, cumpre o ADR-0031 item 3): `member_scopes`, o predicado `app_scope()` e políticas RESTRITIVAS de RLS nas tabelas de rede.

* `member_scopes (tenant_id, user_id, pop_ids uuid[], olt_ids uuid[], updated_by, updated_at)`: **a existência da linha é que restringe** (mesmo com listas vazias ou ids que já não existem: falha
  fechada; apagar uma OLT nunca devolve acesso amplo). Sem linha = provedor inteiro, como sempre. Escrita só pelas funções abaixo (EXECUTE só `fibercore_rbac`, o mesmo padrão da troca de papel,
  0024/0027); a aplicação só lê.
* `app_scope()` lê `app.scope` (definido junto de `app.tenant_id` na MESMA conexão, só pela API, a partir do banco): NULL/'' = sem restrição; `'{id,id}'` = só essas OLTs ('{}' = nenhuma).
* Política `scope_*` `AS RESTRICTIVE` (E lógico com a `tenant_isolation` que já existe) em CADA tabela de dado de rede alcançável por uma permissão de leitura de escopo: as listas, **os totais e
  as contagens, o histórico e o CSV herdam o recorte sem código por endpoint**. Por OLT direta (olts, pon_ports, onus, incidents, onu_state_events, onu_discovery_observations,
  olt_connection_tests, olt_query_latest, olt_metric_samples, olt_profile_snapshots, olt_secret_deliveries); por ONU (incident_onus, onu_cpe_links, associations: só a ONU que o principal vê);
  CPE só se ligado a uma ONU visível (cpes e tudo que tem `cpe_id`); `jobs` pelo alvo; `diagnostic_*` só do próprio autor; `pops` só as que têm OLT visível.
* `app_member_scope_set(p_actor, p_tenant, p_target, p_pops, p_olts)` e `app_member_scope_clear(p_actor, p_tenant, p_target)`: valem o mesmo que as demais funções de equipe (ator com poder de conceder papel, alvo
  não protegido, nunca a si mesmo) e só para papéis que admitem escopo (engineer, noc_n2, noc_n1, support); cada site/OLT tem de existir NA organização. Auditam `member.scope.set|clear`.
Reversível: remove políticas, funções e tabela (volta a todo o provedor para todos). Revision ID: 0058  Revises: 0057
"""
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

SCOPABLE = ("engineer", "noc_n2", "noc_n1", "support")
OLT_DIRECT = {"olts": "id", "pon_ports": "olt_id", "onus": "olt_id", "incidents": "olt_id", "onu_state_events": "olt_id", "onu_discovery_observations": "olt_id", "olt_connection_tests": "olt_id",
              "olt_query_latest": "olt_id", "olt_metric_samples": "olt_id", "olt_profile_snapshots": "olt_id", "olt_secret_deliveries": "olt_id"}
VIA_ONU = ("incident_onus", "onu_cpe_links", "associations")
VIA_CPE = ("cpe_protocol_bindings", "cpe_state", "cpe_config_fields", "cpe_config_changes", "speed_test_runs", "ping_test_runs", "quality_runs", "bench_targets", "bench_authorizations",
           "bench_target_epochs")
OWN_AUTHOR = ("diagnostic_runs", "diagnostic_jobs")
CUR_U = "NULLIF(current_setting('app.user_id', true), '')::uuid"
FUNCS = ["app_member_scope_set(uuid, uuid, uuid, uuid[], uuid[])", "app_member_scope_clear(uuid, uuid, uuid)"]


def _policies() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for t, col in OLT_DIRECT.items():
        out.append((t, f"app_scope() IS NULL OR {col} = ANY(app_scope())"))
    for t in VIA_ONU:
        out.append((t, f"app_scope() IS NULL OR EXISTS (SELECT 1 FROM onus x WHERE x.tenant_id = {t}.tenant_id AND x.id = {t}.onu_id)"))
    out.append(("cpes", "app_scope() IS NULL OR EXISTS (SELECT 1 FROM onu_cpe_links l WHERE l.tenant_id = cpes.tenant_id AND l.cpe_id = cpes.id)"))
    for t in VIA_CPE:
        out.append((t, f"app_scope() IS NULL OR EXISTS (SELECT 1 FROM cpes c WHERE c.tenant_id = {t}.tenant_id AND c.id = {t}.cpe_id)"))
    out.append(("jobs", "app_scope() IS NULL OR (target_type = 'olt' AND target_id = ANY(app_scope())) "
                        "OR (target_type = 'cpe' AND EXISTS (SELECT 1 FROM cpes c WHERE c.tenant_id = jobs.tenant_id AND c.id = jobs.target_id))"))
    out.append(("job_approvals", "app_scope() IS NULL OR EXISTS (SELECT 1 FROM jobs j WHERE j.tenant_id = job_approvals.tenant_id AND j.id = job_approvals.job_id)"))
    for t in OWN_AUTHOR:
        out.append((t, f"app_scope() IS NULL OR requested_by = {CUR_U}"))
    out.append(("pops", "app_scope() IS NULL OR EXISTS (SELECT 1 FROM olts o WHERE o.tenant_id = pops.tenant_id AND o.pop_id = pops.id)"))
    return out


SCOPED_TABLES = [t for t, _ in _policies()]

HEAD = """
  PERFORM set_config('app.tenant_id', p_tenant::text, true);
  PERFORM set_config('app.user_id', p_actor::text, true);
  IF p_actor = p_target THEN RAISE EXCEPTION 'cannot_scope_self'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('tenant-roles:' || p_tenant::text, 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('account:' || p_target::text, 0));
  SELECT role INTO trole FROM tenant_memberships WHERE tenant_id = p_tenant AND user_id = p_target FOR UPDATE;
  IF trole IS NULL THEN RAISE EXCEPTION 'member_not_found'; END IF;
  arole := team_actor_role(p_tenant, p_actor);
  IF arole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = arole) THEN RAISE EXCEPTION 'role_cannot_grant'; END IF;
  IF arole <> 'isp_admin' AND EXISTS (SELECT 1 FROM rbac_protected_roles WHERE role = trole) THEN RAISE EXCEPTION 'target_role_protected'; END IF;
"""

SET_FN = f"""
CREATE FUNCTION app_member_scope_set(p_actor uuid, p_tenant uuid, p_target uuid, p_pops uuid[], p_olts uuid[]) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE arole text; trole text; pops uuid[]; olts uuid[]; had record;
BEGIN
{HEAD}
  IF trole NOT IN ({", ".join(f"'{r}'" for r in SCOPABLE)}) THEN RAISE EXCEPTION 'role_not_scopable'; END IF;
  SELECT COALESCE(array_agg(DISTINCT x ORDER BY x), '{{}}') INTO pops FROM unnest(COALESCE(p_pops, '{{}}'::uuid[])) AS x;
  SELECT COALESCE(array_agg(DISTINCT x ORDER BY x), '{{}}') INTO olts FROM unnest(COALESCE(p_olts, '{{}}'::uuid[])) AS x;
  IF cardinality(pops) + cardinality(olts) NOT BETWEEN 1 AND 200 THEN RAISE EXCEPTION 'scope_invalid'; END IF;
  IF (SELECT count(*) FROM pops_check(p_tenant, pops)) <> cardinality(pops) THEN RAISE EXCEPTION 'scope_target_not_found'; END IF;
  IF (SELECT count(*) FROM olts_check(p_tenant, olts)) <> cardinality(olts) THEN RAISE EXCEPTION 'scope_target_not_found'; END IF;
  SELECT pop_ids, olt_ids INTO had FROM member_scopes WHERE tenant_id = p_tenant AND user_id = p_target;
  INSERT INTO member_scopes (tenant_id, user_id, pop_ids, olt_ids, updated_by, updated_at) VALUES (p_tenant, p_target, pops, olts, p_actor, now())
    ON CONFLICT (tenant_id, user_id) DO UPDATE SET pop_ids = EXCLUDED.pop_ids, olt_ids = EXCLUDED.olt_ids, updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at;
  INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (p_tenant, p_actor, 'member.scope.set', 'user', p_target::text, jsonb_build_object('role', trole, 'pops', pops, 'olts', olts,
            'previous', CASE WHEN had IS NULL THEN NULL ELSE jsonb_build_object('pops', had.pop_ids, 'olts', had.olt_ids) END));
  INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
    VALUES (p_tenant, 'user', p_target, 'member.scope.changed', '1', jsonb_build_object('by', p_actor));
  RETURN jsonb_build_object('pops', pops, 'olts', olts);
END $$;
"""

CLEAR_FN = f"""
CREATE FUNCTION app_member_scope_clear(p_actor uuid, p_tenant uuid, p_target uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE arole text; trole text; had record;
BEGIN
{HEAD}
  DELETE FROM member_scopes WHERE tenant_id = p_tenant AND user_id = p_target RETURNING pop_ids, olt_ids INTO had;
  IF had IS NULL THEN RETURN jsonb_build_object('cleared', false); END IF;
  INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (p_tenant, p_actor, 'member.scope.clear', 'user', p_target::text, jsonb_build_object('role', trole, 'previous', jsonb_build_object('pops', had.pop_ids, 'olts', had.olt_ids)));
  INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
    VALUES (p_tenant, 'user', p_target, 'member.scope.changed', '1', jsonb_build_object('by', p_actor));
  RETURN jsonb_build_object('cleared', true);
END $$;
"""

# the two small existence checks are SQL functions so the setter stays readable; they only count ids that exist in the tenant
CHECKS = """
CREATE FUNCTION pops_check(p_tenant uuid, p_ids uuid[]) RETURNS TABLE (id uuid) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT p.id FROM pops p WHERE p.tenant_id = p_tenant AND p.id = ANY(p_ids) $$;
CREATE FUNCTION olts_check(p_tenant uuid, p_ids uuid[]) RETURNS TABLE (id uuid) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT o.id FROM olts o WHERE o.tenant_id = p_tenant AND o.id = ANY(p_ids) $$;
REVOKE ALL ON FUNCTION pops_check(uuid, uuid[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION olts_check(uuid, uuid[]) FROM PUBLIC;
"""


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE FUNCTION app_scope() RETURNS uuid[] LANGUAGE sql STABLE AS $$
          SELECT CASE WHEN NULLIF(current_setting('app.scope', true), '') IS NULL THEN NULL ELSE current_setting('app.scope', true)::uuid[] END $$;
        GRANT EXECUTE ON FUNCTION app_scope() TO PUBLIC;

        CREATE TABLE member_scopes (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          user_id uuid NOT NULL REFERENCES users_global(id),
          pop_ids uuid[] NOT NULL DEFAULT '{{}}',
          olt_ids uuid[] NOT NULL DEFAULT '{{}}',
          updated_by uuid REFERENCES users_global(id),
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, user_id),
          CHECK (cardinality(pop_ids) + cardinality(olt_ids) <= 200)
        );
        ALTER TABLE member_scopes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE member_scopes FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON member_scopes USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON member_scopes TO fibercore_app;
        """
    )
    for table, expr in _policies():
        op.execute(f"CREATE POLICY scope_restrict ON {table} AS RESTRICTIVE FOR ALL USING ({expr}) WITH CHECK ({expr})")
    op.execute(CHECKS)
    op.execute(SET_FN)
    op.execute(CLEAR_FN)
    op.execute("\n".join(f"REVOKE ALL ON FUNCTION {f} FROM PUBLIC;\nGRANT EXECUTE ON FUNCTION {f} TO fibercore_rbac;" for f in FUNCS))


def downgrade() -> None:
    for table in SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS scope_restrict ON {table}")
    for f in FUNCS + ["pops_check(uuid, uuid[])", "olts_check(uuid, uuid[])", "app_scope()"]:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")
    op.execute("DROP TABLE IF EXISTS member_scopes")
