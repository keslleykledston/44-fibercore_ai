"""members can read the tenants they belong to (workspace picker)

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    cur_u = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    op.execute(
        f"""
        DROP POLICY tenant_isolation ON tenants;
        -- read: the selected tenant OR any tenant the authenticated user is a member of; write: selected tenant only
        CREATE POLICY tenant_read ON tenants FOR SELECT
          USING (id = {cur_t} OR id IN (SELECT tenant_id FROM tenant_memberships WHERE user_id = {cur_u}));
        CREATE POLICY tenant_write ON tenants FOR ALL USING (id = {cur_t}) WITH CHECK (id = {cur_t});
        """
    )


def downgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        DROP POLICY tenant_read ON tenants; DROP POLICY tenant_write ON tenants;
        CREATE POLICY tenant_isolation ON tenants USING (id = {cur_t}) WITH CHECK (id = {cur_t});
        """
    )
