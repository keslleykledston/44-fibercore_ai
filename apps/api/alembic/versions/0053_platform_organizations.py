"""Criação de organização pela tela (ADR-0046 D1): `platform_create_organization` e `platform_list_organizations`

Antes disto só o dono criava uma organização (CLI `create-tenant`, com acesso ao host). Agora a conta marcada operadora da plataforma cria pela tela, e a
role da aplicação continua SEM INSERT em `tenants`: o único caminho é a função abaixo.

`platform_create_organization(p_actor, p_name, p_admin_email, p_admin_name, p_request_id)` (contrato fechado do ADR-0046 D1):
* DONA = a role dona do esquema (quem roda a migração; a role da aplicação não é dona de nada). `SET search_path = pg_catalog, public` e TODA relação/função de `public` vai qualificada
  (`public.tenants`): sem isso uma tabela TEMPORÁRIA homônima, criada pela role da aplicação, entraria à frente no caminho de busca (o `pg_temp` implícito vem primeiro para relações).
* `REVOKE ALL … FROM PUBLIC` e `GRANT EXECUTE` só a `fibercore_app`.
* NÃO confia em contexto de sessão (variáveis forjáveis): o ator é PARÂMETRO e ela mesmo confere, como dona, que ele é conta `is_active AND is_platform_operator` e que há uma sessão viva dele
  com segundo fator recente (`refresh_tokens.mfa_at`, 10 min, ADR-0031). Qualquer falha: `RAISE`, nada criado. O banco não prova QUE o operador iniciou a chamada (R-3 do ADR: a role da
  aplicação escolhe `p_actor`; a prova de MFA é "alguma sessão viva do ator", não "a sessão desta chamada"): declarado, não corrigido aqui.
* valida e limita (nome 2–60 e único sem diferenciar caixa, e-mail ≤ 254 e formato, nome do administrador 1–100), no máximo 5 organizações por hora (contadas na `audit_log`, qualquer ator:
  é o teto do dano de R-3), tudo serializado por uma trava consultiva global.
* numa ÚNICA transação: `tenants` + convite do primeiro `isp_admin` + `audit_log` (`platform.organization.created`: ator alegado, `session_user`, `application_name`, `request_id`) + evento.
* O convite usa o mecanismo de convite existente (`member_invites`, mesmo token de uso único, 72 h, só o SHA-256 guardado). Como o token NÃO pode ser gerado pela API (o contrato da função
  não recebe hash), a função o gera (`gen_random_bytes(32)`, base64url) e o devolve UMA vez. O mecanismo existente assume que quem convidou é membro com direito de conceder o papel
  (`app_invite_accept` confere isso): o operador NÃO é membro. Menor mudança segura: `member_invites.platform_origin` (só funções de dono escrevem; CHECK: só convite do papel `isp_admin`)
  e, nesse caso, o aceite confere que quem convidou ainda é conta ativa e operadora (fail-closed) em vez de papel no provedor. Os demais convites ficam idênticos.
* devolve só `tenant_id` e os dados do convite (id, validade, token).

`platform_list_organizations(p_actor, p_before_at, p_before_id, p_limit)`: a lista do operador, em páginas por cursor (created_at, id), até 200, com `total` e `next` (nunca um corte silencioso; Codex r1) (nome, estado, nº de Edges/OLTs/ONUs, autor alegado e data, estado do convite, se há o par de auditoria da API). Mesma conferência do
ator; só contagens e rótulos, NUNCA linha de cliente final, assinante, OLT, ONU ou Edge.

Os dois leem entre provedores com a role dona: uma política SELECT só do dono (`platform_scan`) por tabela, como 0047/0049 (as escritas rodam com o `app.tenant_id` da nova organização,
restaurado ao fim). `app_metrics_snapshot` ganha `organizations_without_api_trail` (organizações criadas pela função nos últimos 30 dias sem o par `platform.organization.requested`
da rota com o mesmo `request_id`): detecta só chamada FORA da rota (SQL direto), nunca o abuso feito PELA API (ADR-0046 D1, alcance declarado).

Reversível. Revision ID: 0053  Revises: 0051 (a 0052 é da frente de ACS; quem integra corrige o down_revision)
"""
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

SCAN_TABLES = ("tenants", "edges", "olts", "onus", "audit_log", "member_invites")

# the invite mechanism of 0027, with ONE change: an invite created by the platform function (platform_origin) is accepted when its creator is still an active platform operator
ACCEPT_NEW = r"""
CREATE OR REPLACE FUNCTION app_invite_accept(p_hash bytea, p_name text, p_new_hash text, p_existing_verified boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE i record; crole text; uid uuid; act boolean; revoked int := 0;
BEGIN
  SELECT * INTO i FROM member_invites WHERE token_hash = p_hash FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'invite_invalid'; END IF;
  IF i.accepted_at IS NOT NULL THEN RAISE EXCEPTION 'invite_used'; END IF;
  IF i.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'invite_revoked'; END IF;
  IF i.expires_at <= now() THEN RAISE EXCEPTION 'invite_expired'; END IF;
  PERFORM set_config('app.tenant_id', i.tenant_id::text, true);
  IF i.purpose = 'invite' THEN
    IF i.platform_origin THEN
      -- first administrator of an organization created by the platform: whoever invited is a platform operator, not a member; the invite is valid only while that account still is one
      IF NOT EXISTS (SELECT 1 FROM users_global WHERE id = i.created_by AND is_active AND is_platform_operator) THEN RAISE EXCEPTION 'invite_invalid'; END IF;
    ELSE
      crole := team_actor_role(i.tenant_id, i.created_by);        -- whoever invited must still be allowed to hand that role out
      IF crole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = crole AND assignable = i.role) THEN RAISE EXCEPTION 'invite_invalid'; END IF;
    END IF;
    SELECT id, is_active INTO uid, act FROM users_global WHERE lower(email) = i.email FOR UPDATE;
    IF FOUND THEN
      IF NOT act THEN RAISE EXCEPTION 'account_inactive'; END IF;
      IF NOT COALESCE(p_existing_verified, false) THEN RAISE EXCEPTION 'account_exists'; END IF;
    ELSE
      IF p_new_hash IS NULL OR p_name IS NULL OR length(btrim(p_name)) NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'details_required'; END IF;
      INSERT INTO users_global (email, display_name, password_hash) VALUES (i.email, btrim(p_name), p_new_hash) RETURNING id INTO uid;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('tenant-roles:' || i.tenant_id::text, 0));
    IF EXISTS (SELECT 1 FROM tenant_memberships WHERE tenant_id = i.tenant_id AND user_id = uid) THEN RAISE EXCEPTION 'already_member'; END IF;
    INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES (i.tenant_id, uid, i.role);
  ELSE
    uid := i.target_user_id;
    PERFORM 1 FROM users_global WHERE id = uid AND is_active FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'account_inactive'; END IF;
    IF (SELECT count(*) FROM tenant_memberships WHERE user_id = uid) <> 1
       OR NOT EXISTS (SELECT 1 FROM tenant_memberships WHERE user_id = uid AND tenant_id = i.tenant_id) THEN RAISE EXCEPTION 'reset_not_allowed'; END IF;
    IF p_new_hash IS NULL THEN RAISE EXCEPTION 'details_required'; END IF;
    UPDATE users_global SET password_hash = p_new_hash, tokens_valid_after = clock_timestamp() WHERE id = uid;
    UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = uid AND revoked_at IS NULL;
    GET DIAGNOSTICS revoked = ROW_COUNT;
  END IF;
  PERFORM set_config('app.user_id', uid::text, true);
  UPDATE member_invites SET accepted_at = now(), accepted_by = uid WHERE id = i.id;
  INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (i.tenant_id, uid, CASE WHEN i.purpose = 'invite' THEN 'member.invite_accepted' ELSE 'member.password_reset_done' END, 'user', uid::text,
            jsonb_build_object('invite_id', i.id, 'role', i.role, 'revoked_sessions', revoked,
            'name', (SELECT display_name FROM users_global WHERE id = uid), 'email', i.email));
  INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
    VALUES (i.tenant_id, 'user', uid, CASE WHEN i.purpose = 'invite' THEN 'member.joined' ELSE 'member.password_reset' END, '1', jsonb_build_object('role', i.role));
  RETURN jsonb_build_object('purpose', i.purpose, 'user_id', uid);
END $$;
"""

# the 0027 definition, restored by the downgrade
ACCEPT_OLD = ACCEPT_NEW.replace(
    """    IF i.platform_origin THEN
      -- first administrator of an organization created by the platform: whoever invited is a platform operator, not a member; the invite is valid only while that account still is one
      IF NOT EXISTS (SELECT 1 FROM users_global WHERE id = i.created_by AND is_active AND is_platform_operator) THEN RAISE EXCEPTION 'invite_invalid'; END IF;
    ELSE
      crole := team_actor_role(i.tenant_id, i.created_by);        -- whoever invited must still be allowed to hand that role out
      IF crole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = crole AND assignable = i.role) THEN RAISE EXCEPTION 'invite_invalid'; END IF;
    END IF;
""",
    """    crole := team_actor_role(i.tenant_id, i.created_by);        -- whoever invited must still be allowed to hand that role out
    IF crole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = crole AND assignable = i.role) THEN RAISE EXCEPTION 'invite_invalid'; END IF;
""",
)
assert ACCEPT_OLD != ACCEPT_NEW

IN_FLIGHT = ("DISPATCHED", "ACCEPTED", "DEVICE_PENDING", "VERIFYING")


def _snapshot(with_orgs: bool) -> str:
    live = ", ".join(f"'{s}'" for s in IN_FLIGHT)
    extra = (
        """,
            'organizations_without_api_trail', (SELECT count(*) FROM audit_log c WHERE c.action = 'platform.organization.created' AND c.created_at > now() - interval '30 days'
                                                  AND NOT EXISTS (SELECT 1 FROM audit_log r WHERE r.tenant_id = c.tenant_id AND r.action = 'platform.organization.requested'
                                                                   AND r.evidence_redacted ->> 'request_id' = c.evidence_redacted ->> 'request_id'))"""
        if with_orgs else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION app_metrics_snapshot() RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT jsonb_build_object(
            'edges_active', (SELECT count(*) FROM edges WHERE status <> 'revoked'),
            'edges_never_heartbeat', (SELECT count(*) FROM edges WHERE status <> 'revoked' AND last_heartbeat_at IS NULL),
            'edge_heartbeat_age_seconds_max', (SELECT max(extract(epoch FROM now() - last_heartbeat_at)) FROM edges WHERE status <> 'revoked' AND last_heartbeat_at IS NOT NULL),
            'olts_registered', (SELECT count(*) FROM olts o JOIN edges e ON e.tenant_id = o.tenant_id AND e.id = o.edge_id WHERE e.status <> 'revoked'),
            'olts_never_collected', (SELECT count(*) FROM olts o JOIN edges e ON e.tenant_id = o.tenant_id AND e.id = o.edge_id WHERE e.status <> 'revoked' AND o.observed_at IS NULL),
            'olt_collection_age_seconds_max', (SELECT max(extract(epoch FROM now() - o.observed_at)) FROM olts o JOIN edges e ON e.tenant_id = o.tenant_id AND e.id = o.edge_id
                                               WHERE e.status <> 'revoked' AND o.observed_at IS NOT NULL),
            'outbox_unpublished', (SELECT count(*) FROM events_outbox WHERE published_at IS NULL),
            'outbox_oldest_unpublished_age_seconds', (SELECT max(extract(epoch FROM now() - created_at)) FROM events_outbox WHERE published_at IS NULL),
            'jobs', (SELECT COALESCE(jsonb_object_agg(status, n), '{{}}'::jsonb)
                       FROM (SELECT status, count(*) AS n FROM jobs WHERE status IN ({live}) OR updated_at > now() - interval '24 hours' GROUP BY status) s),
            'jobs_in_flight_oldest_age_seconds', (SELECT max(extract(epoch FROM now() - updated_at)) FROM jobs WHERE status IN ({live})){extra}
          )
        $$;
    """


ASSERT_ACTOR = r"""
CREATE FUNCTION platform_assert_actor(p_actor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  -- one answer for "no such account", "inactive" and "not a platform operator": the caller learns nothing about which
  IF p_actor IS NULL OR NOT EXISTS (SELECT 1 FROM public.users_global u WHERE u.id = p_actor AND u.is_active AND u.is_platform_operator) THEN
    RAISE EXCEPTION 'platform_forbidden';
  END IF;
  -- a live session of the actor that proved the second factor in the last 10 minutes (ADR-0031). The database cannot tell WHICH session made the call (R-3 of the ADR)
  IF NOT EXISTS (SELECT 1 FROM public.refresh_tokens r WHERE r.user_id = p_actor AND r.revoked_at IS NULL AND r.expires_at > now() AND r.family_expires_at > now()
                    AND r.mfa_at IS NOT NULL AND r.mfa_at <= clock_timestamp() AND r.mfa_at > clock_timestamp() - interval '10 minutes') THEN
    RAISE EXCEPTION 'mfa_recent_required';
  END IF;
END $$;
"""

CREATE_ORG = r"""
CREATE FUNCTION platform_create_organization(p_actor uuid, p_name text, p_admin_email text, p_admin_name text, p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  nm text; em text; an text; tid uuid := gen_random_uuid(); iid uuid; tok text; exp timestamptz; prev text; masked text;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF p_request_id IS NULL THEN RAISE EXCEPTION 'request_id_required'; END IF;
  IF p_name IS NULL OR length(p_name) > 200 THEN RAISE EXCEPTION 'organization_name_invalid'; END IF;
  nm := regexp_replace(btrim(p_name), '\s+', ' ', 'g');
  IF length(nm) NOT BETWEEN 2 AND 60 OR nm ~ '[[:cntrl:]]' THEN RAISE EXCEPTION 'organization_name_invalid'; END IF;
  IF p_admin_email IS NULL OR length(p_admin_email) > 300 THEN RAISE EXCEPTION 'organization_email_invalid'; END IF;
  em := lower(btrim(p_admin_email));
  IF length(em) > 254 OR em !~ '^[^@[:space:][:cntrl:]]+@[^@[:space:][:cntrl:]]+\.[^@[:space:][:cntrl:]]+$' THEN RAISE EXCEPTION 'organization_email_invalid'; END IF;
  IF p_admin_name IS NOT NULL THEN
    IF length(p_admin_name) > 300 THEN RAISE EXCEPTION 'organization_admin_name_invalid'; END IF;
    an := NULLIF(btrim(p_admin_name), '');
    IF an IS NOT NULL AND (length(an) > 100 OR an ~ '[[:cntrl:]]') THEN RAISE EXCEPTION 'organization_admin_name_invalid'; END IF;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('platform-organization-create', 0));   -- name check, hourly count and insert are one critical section
  IF (SELECT count(*) FROM public.audit_log a WHERE a.action = 'platform.organization.created' AND a.created_at > now() - interval '1 hour') >= 5 THEN
    RAISE EXCEPTION 'organization_rate_limited';
  END IF;
  IF EXISTS (SELECT 1 FROM public.tenants t WHERE lower(btrim(t.name)) = lower(nm)) THEN RAISE EXCEPTION 'organization_name_taken'; END IF;

  prev := current_setting('app.tenant_id', true);
  PERFORM set_config('app.tenant_id', tid::text, true);      -- the writes below run under the new organization's own row-level policy, whatever the owner's attributes
  INSERT INTO public.tenants (id, name) VALUES (tid, nm);
  tok := translate(encode(public.gen_random_bytes(32), 'base64'), '+/=' || chr(10), '-_');
  exp := now() + interval '72 hours';
  INSERT INTO public.member_invites (tenant_id, purpose, email, display_name, role, token_hash, created_by, expires_at, platform_origin)
    VALUES (tid, 'invite', em, an, 'isp_admin', public.digest(convert_to(tok, 'UTF8'), 'sha256'), p_actor, exp, true) RETURNING id INTO iid;
  masked := left(split_part(em, '@', 1), 1) || '***@' || split_part(em, '@', 2);
  INSERT INTO public.audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
    VALUES (tid, p_actor, 'platform.organization.created', 'tenant', tid::text,
            jsonb_build_object('name', nm, 'admin_email', masked, 'invite_id', iid, 'request_id', p_request_id, 'actor_claimed', p_actor,
                               'session_user', session_user, 'application_name', current_setting('application_name', true)));
  INSERT INTO public.events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
    VALUES (tid, 'tenant', tid, 'platform.organization.created', '1', jsonb_build_object('by', p_actor));
  PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
  RETURN jsonb_build_object('tenant_id', tid, 'invite', jsonb_build_object('id', iid, 'token', tok, 'expires_at', exp, 'role', 'isp_admin'));
END $$;
"""

LIST_ORGS = r"""
CREATE FUNCTION platform_list_organizations(p_actor uuid, p_before_at timestamptz DEFAULT NULL, p_before_id uuid DEFAULT NULL, p_limit integer DEFAULT 100) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE lim integer := LEAST(GREATEST(COALESCE(p_limit, 100), 1), 200); out jsonb; total bigint; more boolean; last_at timestamptz; last_id uuid;
BEGIN
  PERFORM public.platform_assert_actor(p_actor);
  IF (p_before_at IS NULL) <> (p_before_id IS NULL) THEN RAISE EXCEPTION 'organization_cursor_invalid'; END IF;
  SELECT count(*) INTO total FROM public.tenants;
  -- keyset page, newest first, by (created_at, id): lim + 1 rows are read to know whether there is more, and the caller is told (never a silent cut)
  WITH page AS (
    SELECT t.id, t.created_at, jsonb_build_object(
      'tenant_id', t.id, 'name', t.name, 'status', t.status, 'created_at', t.created_at,
      'edges', (SELECT count(*) FROM public.edges e WHERE e.tenant_id = t.id AND e.status <> 'revoked'),
      'olts', (SELECT count(*) FROM public.olts l WHERE l.tenant_id = t.id),
      'onus', (SELECT count(*) FROM public.onus n WHERE n.tenant_id = t.id),
      'created_by_name', (SELECT u.display_name FROM public.audit_log a JOIN public.users_global u ON u.id = a.actor_id
                           WHERE a.tenant_id = t.id AND a.action = 'platform.organization.created' LIMIT 1),
      'created_via', CASE WHEN EXISTS (SELECT 1 FROM public.audit_log a WHERE a.tenant_id = t.id AND a.action = 'platform.organization.created') THEN 'screen' ELSE 'cli' END,
      'api_trail', CASE WHEN EXISTS (SELECT 1 FROM public.audit_log a WHERE a.tenant_id = t.id AND a.action = 'platform.organization.created')   -- null = not created by the function (CLI)
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


def upgrade() -> None:
    scans = "\n".join(
        f"          EXECUTE format($p$CREATE POLICY platform_scan ON {t} FOR SELECT TO %I USING (true)$p$, current_user);" for t in SCAN_TABLES
    )
    op.execute(
        f"""
        ALTER TABLE member_invites ADD COLUMN platform_origin boolean NOT NULL DEFAULT false;
        ALTER TABLE member_invites ADD CONSTRAINT invite_platform_origin_shape CHECK (NOT platform_origin OR (purpose = 'invite' AND role = 'isp_admin'));
        DO $$ BEGIN
{scans}
        END $$;
        """
    )
    op.execute(ACCEPT_NEW)
    op.execute(ASSERT_ACTOR)
    op.execute(CREATE_ORG)
    op.execute(LIST_ORGS)
    op.execute(_snapshot(True))
    op.execute(
        """
        REVOKE ALL ON FUNCTION platform_assert_actor(uuid) FROM PUBLIC;
        REVOKE ALL ON FUNCTION platform_create_organization(uuid, text, text, text, uuid) FROM PUBLIC;
        REVOKE ALL ON FUNCTION platform_list_organizations(uuid, timestamptz, uuid, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION platform_create_organization(uuid, text, text, text, uuid) TO fibercore_app;
        GRANT EXECUTE ON FUNCTION platform_list_organizations(uuid, timestamptz, uuid, integer) TO fibercore_app;
        """
    )


def downgrade() -> None:
    drops = " ".join(f"DROP POLICY IF EXISTS platform_scan ON {t};" for t in SCAN_TABLES)
    op.execute(_snapshot(False))
    op.execute(
        "DROP FUNCTION IF EXISTS platform_list_organizations(uuid, timestamptz, uuid, integer); "
        "DROP FUNCTION IF EXISTS platform_create_organization(uuid, text, text, text, uuid); "
        "DROP FUNCTION IF EXISTS platform_assert_actor(uuid);"
    )
    # a pending first-administrator invite would have no valid inviter in the old mechanism: close them before the column that marks them disappears
    op.execute("UPDATE member_invites SET revoked_at = now() WHERE platform_origin AND accepted_at IS NULL AND revoked_at IS NULL")
    op.execute(ACCEPT_OLD)
    op.execute(f"ALTER TABLE member_invites DROP CONSTRAINT invite_platform_origin_shape; ALTER TABLE member_invites DROP COLUMN platform_origin; {drops}")
