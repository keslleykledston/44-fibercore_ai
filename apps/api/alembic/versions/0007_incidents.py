"""NOC incidents (PON mass outage correlation)

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE incidents (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          kind text NOT NULL CHECK (kind IN ('pon_mass_outage')),
          olt_id uuid NOT NULL,
          pon_id uuid NOT NULL,
          dedupe_key text NOT NULL,
          status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
          suspected_cause text NOT NULL DEFAULT 'unknown' CHECK (suspected_cause IN ('fiber_or_los','power','unknown')),
          evidence jsonb NOT NULL DEFAULT '{{}}'::jsonb,   -- counts only, no customer data
          opened_at timestamptz NOT NULL DEFAULT now(),
          resolved_at timestamptz,
          acknowledged_by uuid,
          acknowledged_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id),
          FOREIGN KEY (tenant_id, olt_id, pon_id) REFERENCES pon_ports(tenant_id, olt_id, id),
          CHECK ((status = 'resolved') = (resolved_at IS NOT NULL))
        );
        -- dedupe: at most ONE open incident per key
        CREATE UNIQUE INDEX incidents_open_dedupe_uq ON incidents(tenant_id, dedupe_key) WHERE status = 'open';
        CREATE INDEX incidents_tenant_status_idx ON incidents(tenant_id, status, opened_at DESC);
        ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
        ALTER TABLE incidents FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON incidents USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON incidents TO fibercore_app;
        GRANT UPDATE (status, resolved_at, evidence, suspected_cause, acknowledged_by, acknowledged_at) ON incidents TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS incidents CASCADE")
