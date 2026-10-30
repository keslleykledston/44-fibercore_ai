"""RBAC delivery 2 (ADR-0031): the `access_manager` role, a runtime UPDATE grant on the membership role, and a database-level guard so a workspace
can never be left without an `isp_admin` (the API also checks it under a per-workspace lock; this is the last line of defence)."""
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
        GRANT UPDATE (role) ON tenant_memberships TO fibercore_app;

        CREATE FUNCTION keep_one_isp_admin() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE leaving boolean;
        BEGIN
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
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TRIGGER IF EXISTS keep_one_isp_admin ON tenant_memberships;
        DROP FUNCTION IF EXISTS keep_one_isp_admin();
        REVOKE UPDATE (role) ON tenant_memberships FROM fibercore_app;
        UPDATE tenant_memberships SET role = 'noc_n1' WHERE role = 'access_manager';
        ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
        ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check CHECK (role IN {OLD});
        """
    )
