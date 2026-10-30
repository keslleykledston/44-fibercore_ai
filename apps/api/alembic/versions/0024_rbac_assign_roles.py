"""RBAC delivery 2 (ADR-0031): the `access_manager` role and the ONLY way to change a membership role.

* A dedicated database role `fibercore_rbac` (own password, like `fibercore_worker`) is the only one that may EXECUTE `app_change_member_role`, a
  SECURITY DEFINER function that validates the actor and the transition in SQL and does the whole change in ONE transaction (role, session revocation,
  audit, outbox). The runtime role `fibercore_app` has no UPDATE on the column and no EXECUTE on the function, so SQL that reaches the database through
  the application's normal connection (injection) cannot change a role, even by forging the session settings that RLS reads.
* Triggers keep at least one active `isp_admin` in every workspace (role change, delete, account deactivation), serialised by the per-workspace lock.
"""
import os
import re

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

OLD = "('isp_admin','engineer','noc_n2','noc_n1','support','auditor','platform_support')"
NEW = "('isp_admin','access_manager','engineer','noc_n2','noc_n1','support','auditor','platform_support')"


def _pw() -> str:
    pw = os.environ.get("RBAC_DB_PASSWORD", "")
    if len(pw) < 16 or not re.fullmatch(r"[A-Za-z0-9_.\-]+", pw):
        raise RuntimeError("RBAC_DB_PASSWORD must be >=16 chars of [A-Za-z0-9_.-]")
    return pw


def upgrade() -> None:
    pw = _pw()
    op.execute(  # noqa: S608 - pw validated by the regex above
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fibercore_rbac') THEN
            CREATE ROLE fibercore_rbac LOGIN;
          END IF;
        END $$;
        ALTER ROLE fibercore_rbac LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{pw}';
        GRANT USAGE ON SCHEMA public TO fibercore_rbac;

        ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
        ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check CHECK (role IN {NEW});

        CREATE TABLE rbac_role_grants (granter text NOT NULL, assignable text NOT NULL, PRIMARY KEY (granter, assignable));
        INSERT INTO rbac_role_grants VALUES
          ('isp_admin','isp_admin'),('isp_admin','access_manager'),('isp_admin','engineer'),('isp_admin','noc_n2'),('isp_admin','noc_n1'),
          ('isp_admin','support'),('isp_admin','auditor'),
          ('access_manager','engineer'),('access_manager','noc_n2'),('access_manager','noc_n1'),('access_manager','support'),('access_manager','auditor');
        CREATE TABLE rbac_protected_roles (role text PRIMARY KEY);
        INSERT INTO rbac_protected_roles VALUES ('isp_admin'),('access_manager'),('platform_support'),('edge_agent');

        CREATE FUNCTION app_change_member_role(p_actor uuid, p_tenant uuid, p_target uuid, p_new text, p_reason text) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE actor_role text; old_role text; revoked int; others int;
        BEGIN
          PERFORM set_config('app.tenant_id', p_tenant::text, true);   -- RLS context for an owner that is not a superuser
          PERFORM set_config('app.user_id', p_actor::text, true);
          IF p_actor = p_target THEN RAISE EXCEPTION 'cannot_change_own_role'; END IF;
          IF p_reason IS NULL OR length(btrim(p_reason)) NOT BETWEEN 3 AND 200 THEN RAISE EXCEPTION 'reason_required'; END IF;
          -- lock order, the same for every caller: 1) the target's ACCOUNT row, 2) the workspace lock, 3) the account advisory lock, 4) the membership row
          PERFORM 1 FROM users_global WHERE id = p_target AND is_active FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'member_not_found'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended('tenant-roles:' || p_tenant::text, 0));
          PERFORM pg_advisory_xact_lock(hashtextextended('account:' || p_target::text, 0));
          SELECT role INTO old_role FROM tenant_memberships WHERE tenant_id = p_tenant AND user_id = p_target FOR UPDATE;
          IF old_role IS NULL THEN RAISE EXCEPTION 'member_not_found'; END IF;
          SELECT role INTO actor_role FROM tenant_memberships WHERE tenant_id = p_tenant AND user_id = p_actor;
          IF actor_role IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = actor_role) THEN RAISE EXCEPTION 'role_cannot_grant'; END IF;
          IF NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = actor_role AND assignable = p_new) THEN RAISE EXCEPTION 'role_not_assignable'; END IF;
          IF actor_role <> 'isp_admin' AND EXISTS (SELECT 1 FROM rbac_protected_roles WHERE role = old_role) THEN RAISE EXCEPTION 'target_role_protected'; END IF;
          IF old_role = p_new THEN RAISE EXCEPTION 'role_unchanged'; END IF;
          IF old_role = 'isp_admin' THEN
            SELECT count(*) INTO others FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id
             WHERE m.tenant_id = p_tenant AND m.role = 'isp_admin' AND u.is_active AND m.user_id <> p_target;
            IF others = 0 THEN RAISE EXCEPTION 'last_isp_admin'; END IF;
          END IF;
          UPDATE tenant_memberships SET role = p_new WHERE tenant_id = p_tenant AND user_id = p_target;
          -- the member's old tokens (they carry the old role's power) and refresh tokens end now; sessions belong to the ACCOUNT, so this reaches every workspace
          UPDATE users_global SET tokens_valid_after = clock_timestamp() WHERE id = p_target;
          UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = p_target AND revoked_at IS NULL;
          GET DIAGNOSTICS revoked = ROW_COUNT;
          INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
            VALUES (p_tenant, p_actor, 'member.role_change', 'user', p_target::text,
                    jsonb_build_object('from', old_role, 'to', p_new, 'reason', btrim(p_reason), 'revoked_sessions', revoked));
          INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
            VALUES (p_tenant, 'user', p_target, 'member.role_change', '1', jsonb_build_object('by', p_actor, 'from', old_role, 'to', p_new));
          RETURN jsonb_build_object('previous_role', old_role, 'revoked_sessions', revoked);
        END $$;
        REVOKE ALL ON FUNCTION app_change_member_role(uuid, uuid, uuid, text, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_change_member_role(uuid, uuid, uuid, text, text) TO fibercore_rbac;

        CREATE FUNCTION keep_one_isp_admin() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE leaving boolean;
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended('tenant-roles:' || OLD.tenant_id::text, 0));  -- serialise with every other role change of the workspace
          -- a membership that WAS an isp_admin stops being one (role change) or goes away: the workspace must still have another
          IF TG_OP = 'DELETE' THEN
            leaving := OLD.role = 'isp_admin';
          ELSE
            leaving := OLD.role = 'isp_admin' AND NEW.role <> 'isp_admin';
          END IF;
          IF leaving AND NOT EXISTS (
            SELECT 1 FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id
             WHERE m.tenant_id = OLD.tenant_id AND m.role = 'isp_admin' AND u.is_active AND m.user_id <> OLD.user_id
          ) THEN
            RAISE EXCEPTION 'a workspace must keep at least one active isp_admin' USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER keep_one_isp_admin BEFORE UPDATE OF role OR DELETE ON tenant_memberships
          FOR EACH ROW EXECUTE FUNCTION keep_one_isp_admin();

        -- deactivating an ACCOUNT is the same thing as taking its administrator role away in every workspace it administers
        CREATE FUNCTION keep_one_isp_admin_on_deactivate() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE ws uuid;
        BEGIN
          IF OLD.is_active AND NOT NEW.is_active THEN
            FOR ws IN SELECT tenant_id FROM tenant_memberships WHERE user_id = OLD.id AND role = 'isp_admin' ORDER BY tenant_id LOOP
              PERFORM pg_advisory_xact_lock(hashtextextended('tenant-roles:' || ws::text, 0));
              IF NOT EXISTS (
                SELECT 1 FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id
                 WHERE m.tenant_id = ws AND m.role = 'isp_admin' AND u.is_active AND m.user_id <> OLD.id
              ) THEN
                RAISE EXCEPTION 'a workspace must keep at least one active isp_admin' USING ERRCODE = 'check_violation';
              END IF;
            END LOOP;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER keep_one_isp_admin_on_deactivate BEFORE UPDATE OF is_active ON users_global
          FOR EACH ROW EXECUTE FUNCTION keep_one_isp_admin_on_deactivate();
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TRIGGER IF EXISTS keep_one_isp_admin_on_deactivate ON users_global;
        DROP FUNCTION IF EXISTS keep_one_isp_admin_on_deactivate();
        DROP TRIGGER IF EXISTS keep_one_isp_admin ON tenant_memberships;
        DROP FUNCTION IF EXISTS keep_one_isp_admin();
        DROP FUNCTION IF EXISTS app_change_member_role(uuid, uuid, uuid, text, text);
        DROP TABLE IF EXISTS rbac_role_grants, rbac_protected_roles;
        UPDATE tenant_memberships SET role = 'noc_n1' WHERE role = 'access_manager';
        ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
        ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check CHECK (role IN {OLD});
        REVOKE USAGE ON SCHEMA public FROM fibercore_rbac;
        """
    )
