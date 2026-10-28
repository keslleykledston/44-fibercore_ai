"""edges table (edge-fleet) + edge_agent role

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ROLES = "('isp_admin','engineer','noc_n2','noc_n1','support','auditor','platform_support','edge_agent')"


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
        ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check CHECK (role IN {ROLES});
        ALTER TABLE service_accounts DROP CONSTRAINT service_accounts_role_check;
        ALTER TABLE service_accounts ADD CONSTRAINT service_accounts_role_check CHECK (role IN {ROLES});

        CREATE TABLE edges (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          name text NOT NULL,
          site_name text,
          certificate_serial text,
          version text,
          last_heartbeat_at timestamptz,
          status text NOT NULL DEFAULT 'unknown' CHECK (status IN ('unknown','online','offline','revoked')),
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, name)
        );
        ALTER TABLE edges ENABLE ROW LEVEL SECURITY;
        ALTER TABLE edges FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON edges USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        -- Registration/revocation is an owner (CLI) operation. Runtime may only record heartbeats.
        -- An edge_agent service account is bound to exactly ONE edge; other roles never carry an edge.
        ALTER TABLE service_accounts ADD COLUMN edge_id uuid;
        ALTER TABLE service_accounts ADD CONSTRAINT service_accounts_edge_fk
          FOREIGN KEY (tenant_id, edge_id) REFERENCES edges(tenant_id, id);
        ALTER TABLE service_accounts ADD CONSTRAINT service_accounts_edge_role_ck
          CHECK ((role = 'edge_agent') = (edge_id IS NOT NULL));
        GRANT SELECT ON edges TO fibercore_app;
        GRANT UPDATE (version, last_heartbeat_at, status) ON edges TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE service_accounts DROP COLUMN IF EXISTS edge_id CASCADE")
    op.execute("DROP TABLE IF EXISTS edges")
