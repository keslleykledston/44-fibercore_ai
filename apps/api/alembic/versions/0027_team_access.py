"""Team management for people who are not engineers (owner request 2026-10-30): invite a person, remove a person, reset a password, change one's own.

Until now a person could only be added with a command on the server. This adds, with the same discipline as the role change (ADR-0031):

* `member_invites`: an invite or a password-reset LINK. The token is shown once to whoever created it; only its SHA-256 is stored. An invite never
  carries a password: the invited person chooses theirs. Valid at most 72 h, one pending per (workspace, e-mail, purpose).
* SECURITY DEFINER functions, executable only by the dedicated `fibercore_rbac` connection: create/revoke an invite, create a reset link, look up and ACCEPT
  a link (the unauthenticated part: it can only do what the stored row says), remove a member, change one's own password. Every one audits and emits an event.
* Rules reuse `rbac_role_grants` / `rbac_protected_roles`: an access manager cannot invite an administrator or reset the password of a protected target;
  the last administrator cannot be removed (the trigger of 0024 answers); an administrator of one workspace cannot reset the password of an account that
  also belongs to another workspace (that would be taking over a person in somebody else's workspace).

Revision ID: 0027
Revises: 0026
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

ROLES = "('isp_admin','access_manager','engineer','noc_n2','noc_n1','support','auditor')"


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE member_invites (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          purpose text NOT NULL CHECK (purpose IN ('invite','reset')),
          email text NOT NULL CHECK (email = lower(btrim(email)) AND length(email) <= 254 AND email ~ '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'),
          display_name text CHECK (display_name IS NULL OR length(btrim(display_name)) BETWEEN 1 AND 100),
          role text CHECK (role IN {ROLES}),
          target_user_id uuid REFERENCES users_global(id),
          token_hash bytea NOT NULL UNIQUE CHECK (length(token_hash) = 32),
          created_by uuid NOT NULL REFERENCES users_global(id),
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          accepted_at timestamptz,
          accepted_by uuid REFERENCES users_global(id),
          revoked_at timestamptz,
          revoked_by uuid REFERENCES users_global(id),
          CONSTRAINT invite_max_72h CHECK (expires_at > created_at AND expires_at <= created_at + interval '72 hours'),
          CONSTRAINT invite_shape CHECK ((purpose = 'invite') = (role IS NOT NULL) AND (purpose = 'reset') = (target_user_id IS NOT NULL)),
          CONSTRAINT invite_one_end CHECK (accepted_at IS NULL OR revoked_at IS NULL)
        );
        CREATE UNIQUE INDEX member_invites_one_pending ON member_invites (tenant_id, email, purpose) WHERE accepted_at IS NULL AND revoked_at IS NULL;
        CREATE INDEX member_invites_tenant_idx ON member_invites (tenant_id, created_at DESC);
        ALTER TABLE member_invites ENABLE ROW LEVEL SECURITY;
        ALTER TABLE member_invites FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON member_invites USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON member_invites TO fibercore_app;

        -- ---- helpers --------------------------------------------------------------------------------------------------
        CREATE FUNCTION team_actor_role(p_tenant uuid, p_actor uuid) RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT m.role FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id
           WHERE m.tenant_id = p_tenant AND m.user_id = p_actor AND u.is_active
        $$;
        REVOKE ALL ON FUNCTION team_actor_role(uuid, uuid) FROM PUBLIC;

        -- ---- invite ---------------------------------------------------------------------------------------------------
        CREATE FUNCTION app_invite_create(p_actor uuid, p_tenant uuid, p_email text, p_name text, p_role text, p_hash bytea, p_hours int) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE arole text; em text := lower(btrim(p_email)); iid uuid; exp timestamptz;
        BEGIN
          PERFORM set_config('app.tenant_id', p_tenant::text, true);
          PERFORM set_config('app.user_id', p_actor::text, true);
          arole := team_actor_role(p_tenant, p_actor);
          IF arole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = arole) THEN RAISE EXCEPTION 'role_cannot_grant'; END IF;
          IF NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = arole AND assignable = p_role) THEN RAISE EXCEPTION 'role_not_assignable'; END IF;
          IF p_hours IS NULL OR p_hours NOT BETWEEN 1 AND 72 THEN RAISE EXCEPTION 'validity_invalid'; END IF;
          IF em !~ '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$' OR length(em) > 254 THEN RAISE EXCEPTION 'email_invalid'; END IF;
          IF p_name IS NOT NULL AND length(btrim(p_name)) NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'name_invalid'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended('invite|' || p_tenant::text || '|' || em, 0));
          IF EXISTS (SELECT 1 FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id WHERE m.tenant_id = p_tenant AND lower(u.email) = em) THEN
            RAISE EXCEPTION 'already_member';
          END IF;
          UPDATE member_invites SET revoked_at = now(), revoked_by = p_actor
           WHERE tenant_id = p_tenant AND email = em AND purpose = 'invite' AND accepted_at IS NULL AND revoked_at IS NULL;
          exp := now() + make_interval(hours => p_hours);
          INSERT INTO member_invites (tenant_id, purpose, email, display_name, role, token_hash, created_by, expires_at)
            VALUES (p_tenant, 'invite', em, NULLIF(btrim(p_name), ''), p_role, p_hash, p_actor, exp) RETURNING id INTO iid;
          INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
            VALUES (p_tenant, p_actor, 'member.invite', 'invite', iid::text, jsonb_build_object('email', em, 'role', p_role, 'hours', p_hours));
          INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
            VALUES (p_tenant, 'invite', iid, 'member.invited', '1', jsonb_build_object('by', p_actor, 'role', p_role));
          RETURN jsonb_build_object('id', iid, 'expires_at', exp, 'email', em, 'role', p_role);
        END $$;

        CREATE FUNCTION app_invite_revoke(p_actor uuid, p_tenant uuid, p_invite uuid) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE arole text; i record;
        BEGIN
          PERFORM set_config('app.tenant_id', p_tenant::text, true);
          PERFORM set_config('app.user_id', p_actor::text, true);
          arole := team_actor_role(p_tenant, p_actor);
          IF arole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = arole) THEN RAISE EXCEPTION 'role_cannot_grant'; END IF;
          SELECT id, purpose, role, accepted_at, revoked_at INTO i FROM member_invites WHERE tenant_id = p_tenant AND id = p_invite FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'invite_not_found'; END IF;
          IF i.accepted_at IS NOT NULL OR i.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'invite_not_open'; END IF;
          IF i.purpose = 'invite' AND NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = arole AND assignable = i.role) THEN RAISE EXCEPTION 'role_not_assignable'; END IF;
          UPDATE member_invites SET revoked_at = now(), revoked_by = p_actor WHERE tenant_id = p_tenant AND id = p_invite;
          INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
            VALUES (p_tenant, p_actor, 'member.invite_revoke', 'invite', p_invite::text, jsonb_build_object('purpose', i.purpose));
          RETURN jsonb_build_object('id', p_invite);
        END $$;

        -- ---- password reset link ---------------------------------------------------------------------------------------
        CREATE FUNCTION app_reset_create(p_actor uuid, p_tenant uuid, p_target uuid, p_hash bytea, p_hours int) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE arole text; trole text; em text; iid uuid; exp timestamptz; n int;
        BEGIN
          PERFORM set_config('app.tenant_id', p_tenant::text, true);
          PERFORM set_config('app.user_id', p_actor::text, true);
          IF p_actor = p_target THEN RAISE EXCEPTION 'use_change_password'; END IF;
          arole := team_actor_role(p_tenant, p_actor);
          IF arole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = arole) THEN RAISE EXCEPTION 'role_cannot_grant'; END IF;
          IF p_hours IS NULL OR p_hours NOT BETWEEN 1 AND 24 THEN RAISE EXCEPTION 'validity_invalid'; END IF;
          PERFORM 1 FROM users_global WHERE id = p_target AND is_active FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'member_not_found'; END IF;
          SELECT role INTO trole FROM tenant_memberships WHERE tenant_id = p_tenant AND user_id = p_target;
          IF trole IS NULL THEN RAISE EXCEPTION 'member_not_found'; END IF;
          IF arole <> 'isp_admin' AND EXISTS (SELECT 1 FROM rbac_protected_roles WHERE role = trole) THEN RAISE EXCEPTION 'target_role_protected'; END IF;
          -- one account, several workspaces: no administrator of ONE of them may take the person over
          SELECT count(*) INTO n FROM tenant_memberships WHERE user_id = p_target;
          IF n <> 1 THEN RAISE EXCEPTION 'account_shared'; END IF;
          IF EXISTS (SELECT 1 FROM membership_delegations WHERE user_id = p_target) THEN RAISE EXCEPTION 'account_shared'; END IF;
          SELECT lower(email) INTO em FROM users_global WHERE id = p_target;
          PERFORM pg_advisory_xact_lock(hashtextextended('reset|' || p_tenant::text || '|' || em, 0));
          UPDATE member_invites SET revoked_at = now(), revoked_by = p_actor
           WHERE tenant_id = p_tenant AND email = em AND purpose = 'reset' AND accepted_at IS NULL AND revoked_at IS NULL;
          exp := now() + make_interval(hours => p_hours);
          INSERT INTO member_invites (tenant_id, purpose, email, target_user_id, token_hash, created_by, expires_at)
            VALUES (p_tenant, 'reset', em, p_target, p_hash, p_actor, exp) RETURNING id INTO iid;
          INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
            VALUES (p_tenant, p_actor, 'member.password_reset_link', 'user', p_target::text, jsonb_build_object('invite_id', iid, 'hours', p_hours));
          INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
            VALUES (p_tenant, 'user', p_target, 'member.password_reset_link', '1', jsonb_build_object('by', p_actor));
          RETURN jsonb_build_object('id', iid, 'expires_at', exp);
        END $$;

        -- ---- the unauthenticated half: look at a link, accept a link ---------------------------------------------------
        CREATE FUNCTION app_invite_lookup(p_hash bytea) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE i record; tname text; inviter text; u record; st text;
        BEGIN
          SELECT * INTO i FROM member_invites WHERE token_hash = p_hash;
          IF NOT FOUND THEN RETURN jsonb_build_object('state', 'invalid'); END IF;
          st := CASE WHEN i.accepted_at IS NOT NULL THEN 'used' WHEN i.revoked_at IS NOT NULL THEN 'revoked' WHEN i.expires_at <= now() THEN 'expired' ELSE 'valid' END;
          IF st <> 'valid' THEN RETURN jsonb_build_object('state', st); END IF;
          SELECT name INTO tname FROM tenants WHERE id = i.tenant_id;
          SELECT display_name INTO inviter FROM users_global WHERE id = i.created_by;
          SELECT id, password_hash, is_active INTO u FROM users_global WHERE lower(email) = i.email;
          RETURN jsonb_build_object('state', 'valid', 'purpose', i.purpose, 'tenant_name', tname, 'email', i.email, 'display_name', i.display_name, 'role', i.role,
                                    'inviter', inviter, 'expires_at', i.expires_at, 'account_exists', u.id IS NOT NULL,
                                    'account_active', COALESCE(u.is_active, true), 'password_hash', CASE WHEN i.purpose = 'invite' THEN u.password_hash END);
        END $$;

        CREATE FUNCTION app_invite_accept(p_hash bytea, p_name text, p_new_hash text, p_existing_verified boolean) RETURNS jsonb
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
            crole := team_actor_role(i.tenant_id, i.created_by);        -- whoever invited must still be allowed to hand that role out
            IF crole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = crole AND assignable = i.role) THEN RAISE EXCEPTION 'invite_invalid'; END IF;
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

        -- ---- remove a person from the workspace ------------------------------------------------------------------------
        CREATE FUNCTION app_member_remove(p_actor uuid, p_tenant uuid, p_target uuid, p_reason text) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE arole text; trole text;
        BEGIN
          PERFORM set_config('app.tenant_id', p_tenant::text, true);
          PERFORM set_config('app.user_id', p_actor::text, true);
          IF p_actor = p_target THEN RAISE EXCEPTION 'cannot_remove_self'; END IF;
          IF p_reason IS NULL OR length(btrim(p_reason)) NOT BETWEEN 3 AND 200 THEN RAISE EXCEPTION 'reason_required'; END IF;
          PERFORM 1 FROM users_global WHERE id = p_target FOR UPDATE;     -- same lock order as the role change: the account row first
          IF NOT FOUND THEN RAISE EXCEPTION 'member_not_found'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended('tenant-roles:' || p_tenant::text, 0));
          PERFORM pg_advisory_xact_lock(hashtextextended('account:' || p_target::text, 0));
          SELECT role INTO trole FROM tenant_memberships WHERE tenant_id = p_tenant AND user_id = p_target FOR UPDATE;
          IF trole IS NULL THEN RAISE EXCEPTION 'member_not_found'; END IF;
          arole := team_actor_role(p_tenant, p_actor);
          IF arole IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = arole) THEN RAISE EXCEPTION 'role_cannot_grant'; END IF;
          IF arole <> 'isp_admin' AND EXISTS (SELECT 1 FROM rbac_protected_roles WHERE role = trole) THEN RAISE EXCEPTION 'target_role_protected'; END IF;
          DELETE FROM tenant_memberships WHERE tenant_id = p_tenant AND user_id = p_target;   -- the 0024 trigger refuses the last isp_admin
          UPDATE member_invites SET revoked_at = now(), revoked_by = p_actor
           WHERE tenant_id = p_tenant AND target_user_id = p_target AND accepted_at IS NULL AND revoked_at IS NULL;
          INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
            VALUES (p_tenant, p_actor, 'member.remove', 'user', p_target::text, jsonb_build_object('role', trole, 'reason', btrim(p_reason),
                    'name', (SELECT display_name FROM users_global WHERE id = p_target), 'email', (SELECT lower(email) FROM users_global WHERE id = p_target)));
          INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
            VALUES (p_tenant, 'user', p_target, 'member.removed', '1', jsonb_build_object('by', p_actor, 'role', trole));
          RETURN jsonb_build_object('previous_role', trole);
        END $$;

        -- ---- a person changes THEIR OWN password (the API verified the current one) -------------------------------------
        CREATE FUNCTION app_password_change(p_user uuid, p_expected_hash text, p_new_hash text) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE revoked int;
        BEGIN
          IF p_new_hash IS NULL OR length(p_new_hash) < 20 THEN RAISE EXCEPTION 'details_required'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended('account:' || p_user::text, 0));
          -- compare-and-swap: the password the API VERIFIED must still be the stored one, or a concurrent change already happened
          UPDATE users_global SET password_hash = p_new_hash, tokens_valid_after = clock_timestamp()
           WHERE id = p_user AND is_active AND password_hash IS NOT DISTINCT FROM p_expected_hash;
          IF NOT FOUND THEN RAISE EXCEPTION 'password_changed'; END IF;
          UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = p_user AND revoked_at IS NULL;
          GET DIAGNOSTICS revoked = ROW_COUNT;
          INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
            SELECT tenant_id, p_user, 'account.password_change', 'user', p_user::text, jsonb_build_object('revoked_sessions', revoked)
              FROM tenant_memberships WHERE user_id = p_user;
          RETURN jsonb_build_object('revoked_sessions', revoked);
        END $$;

        REVOKE ALL ON FUNCTION app_invite_create(uuid, uuid, text, text, text, bytea, int) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app_invite_revoke(uuid, uuid, uuid) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app_reset_create(uuid, uuid, uuid, bytea, int) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app_invite_lookup(bytea) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app_invite_accept(bytea, text, text, boolean) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app_member_remove(uuid, uuid, uuid, text) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app_password_change(uuid, text, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_invite_create(uuid, uuid, text, text, text, bytea, int) TO fibercore_rbac;
        GRANT EXECUTE ON FUNCTION app_invite_revoke(uuid, uuid, uuid) TO fibercore_rbac;
        GRANT EXECUTE ON FUNCTION app_reset_create(uuid, uuid, uuid, bytea, int) TO fibercore_rbac;
        GRANT EXECUTE ON FUNCTION app_invite_lookup(bytea) TO fibercore_rbac;
        GRANT EXECUTE ON FUNCTION app_invite_accept(bytea, text, text, boolean) TO fibercore_rbac;
        GRANT EXECUTE ON FUNCTION app_member_remove(uuid, uuid, uuid, text) TO fibercore_rbac;
        GRANT EXECUTE ON FUNCTION app_password_change(uuid, text, text) TO fibercore_rbac;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS app_password_change(uuid, text, text);
        DROP FUNCTION IF EXISTS app_member_remove(uuid, uuid, uuid, text);
        DROP FUNCTION IF EXISTS app_invite_accept(bytea, text, text, boolean);
        DROP FUNCTION IF EXISTS app_invite_lookup(bytea);
        DROP FUNCTION IF EXISTS app_reset_create(uuid, uuid, uuid, bytea, int);
        DROP FUNCTION IF EXISTS app_invite_revoke(uuid, uuid, uuid);
        DROP FUNCTION IF EXISTS app_invite_create(uuid, uuid, text, text, text, bytea, int);
        DROP FUNCTION IF EXISTS team_actor_role(uuid, uuid);
        DROP TABLE IF EXISTS member_invites;
        """
    )
