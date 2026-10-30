"""RBAC delivery 2 (ADR-0031): the `access_manager` role; the ONLY way for the runtime role to change a membership role is a narrow SECURITY DEFINER function
that re-validates the actor and the transition in SQL (no column grant); and a trigger so a workspace can never be left without an `isp_admin`.
The API checks the same rules first (clear error codes, per-workspace lock); the database is the backstop."""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

OLD = "('isp_admin','engineer','noc_n2','noc_n1','support','auditor','platform_support')"
NEW = "('isp_admin','access_manager','engineer','noc_n2','noc_n1','support','auditor','platform_support')"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
        ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check CHECK (role IN {NEW});

        CREATE TABLE rbac_role_grants (granter text NOT NULL, assignable text NOT NULL, PRIMARY KEY (granter, assignable));
        INSERT INTO rbac_role_grants VALUES
          ('isp_admin','isp_admin'),('isp_admin','access_manager'),('isp_admin','engineer'),('isp_admin','noc_n2'),('isp_admin','noc_n1'),
          ('isp_admin','support'),('isp_admin','auditor'),
          ('access_manager','engineer'),('access_manager','noc_n2'),('access_manager','noc_n1'),('access_manager','support'),('access_manager','auditor');
        CREATE TABLE rbac_protected_roles (role text PRIMARY KEY);
        INSERT INTO rbac_protected_roles VALUES ('isp_admin'),('access_manager'),('platform_support'),('edge_agent');

        CREATE FUNCTION app_change_member_role(p_target uuid, p_new text) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
          a uuid := NULLIF(current_setting('app.user_id', true), '')::uuid;
          actor_role text; old_role text;
        BEGIN
          IF t IS NULL OR a IS NULL OR a = p_target THEN
            RAISE EXCEPTION 'role change refused' USING ERRCODE = 'insufficient_privilege';
          END IF;
          -- lock order, the same as the API and the deactivation trigger: 1) the target's ACCOUNT row, 2) the workspace lock
          PERFORM 1 FROM users_global WHERE id = p_target FOR UPDATE;
          -- the SAME per-workspace lock the API takes: direct callers of this function serialise too (two administrators cannot demote each other at once)
          PERFORM pg_advisory_xact_lock(hashtextextended('tenant-roles:' || t::text, 0));
          SELECT role INTO actor_role FROM tenant_memberships WHERE tenant_id = t AND user_id = a;
          SELECT role INTO old_role FROM tenant_memberships WHERE tenant_id = t AND user_id = p_target FOR UPDATE;
          IF actor_role IS NULL OR old_role IS NULL OR old_role = p_new
             OR NOT EXISTS (SELECT 1 FROM rbac_role_grants WHERE granter = actor_role AND assignable = p_new)
             OR (actor_role <> 'isp_admin' AND EXISTS (SELECT 1 FROM rbac_protected_roles WHERE role = old_role)) THEN
            RAISE EXCEPTION 'role change refused' USING ERRCODE = 'insufficient_privilege';
          END IF;
          UPDATE tenant_memberships SET role = p_new WHERE tenant_id = t AND user_id = p_target;
          RETURN old_role;
        END $$;
        REVOKE ALL ON FUNCTION app_change_member_role(uuid, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_change_member_role(uuid, text) TO fibercore_app;

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
        DROP FUNCTION IF EXISTS app_change_member_role(uuid, text);
        DROP TABLE IF EXISTS rbac_role_grants, rbac_protected_roles;
        UPDATE tenant_memberships SET role = 'noc_n1' WHERE role = 'access_manager';
        ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
        ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check CHECK (role IN {OLD});
        """
    )
