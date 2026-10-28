"""ONU state transitions + incident membership (mass-outage correlation on recent drops, not on absolute offline ratio)

Real fleets carry many chronically-offline ONUs (a measured MA5608T had 37% of its ONTs offline for months). The old
rule (>=80% of a complete PON offline) would open a permanent false incident on such PONs. The correlation now looks at
ONUs that DROPPED recently, which needs the moment of the online->down transition, and an incident remembers which ONUs
it covers so it neither resolves just because the drop window expired nor grows to include unrelated chronic ones.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        ALTER TABLE onus
          ADD COLUMN last_online_at timestamptz,  -- last snapshot that saw the ONU online
          ADD COLUMN down_since timestamptz;      -- snapshot where an ONU seen online was first seen down; NULL = never observed dropping

        CREATE TABLE incident_onus (
          tenant_id uuid NOT NULL,
          incident_id uuid NOT NULL,
          onu_id uuid NOT NULL,
          PRIMARY KEY (tenant_id, incident_id, onu_id),
          FOREIGN KEY (tenant_id, incident_id) REFERENCES incidents(tenant_id, id) ON DELETE CASCADE,
          FOREIGN KEY (tenant_id, onu_id) REFERENCES onus(tenant_id, id) ON DELETE CASCADE
        );
        ALTER TABLE incident_onus ENABLE ROW LEVEL SECURITY;
        ALTER TABLE incident_onus FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON incident_onus USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON incident_onus TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS incident_onus; "
        "ALTER TABLE onus DROP COLUMN IF EXISTS down_since, DROP COLUMN IF EXISTS last_online_at;"
    )
