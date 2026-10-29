"""ONU <-> CPE links with evidence and human confirmation (ADR-0021, FC22-004)

The ONU (seen by the OLT) and the CPE (seen by the ACS) are identities from DIFFERENT sources. A link is a claim with evidence and a
confidence; automatic suggestions stay `suggested` until a person confirms them. One confirmed link per ONU and per CPE.

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE onu_cpe_links (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          onu_id uuid NOT NULL,
          cpe_id uuid NOT NULL,
          status text NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested','confirmed','rejected')),
          confidence numeric(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
          evidence jsonb NOT NULL,   -- no default: a link without the rule that produced it cannot exist
          created_at timestamptz NOT NULL DEFAULT now(),
          reviewed_by uuid,
          reviewed_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, onu_id) REFERENCES onus(tenant_id, id),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id),
          CHECK ((status = 'suggested') = (reviewed_by IS NULL)),
          CHECK ((jsonb_typeof(evidence->'rule') = 'string') IS TRUE)  -- NULL (rule absent) must not pass a CHECK
        );
        CREATE UNIQUE INDEX onu_cpe_links_pair_uq ON onu_cpe_links (tenant_id, onu_id, cpe_id);
        CREATE UNIQUE INDEX onu_cpe_links_one_confirmed_per_onu ON onu_cpe_links (tenant_id, onu_id) WHERE status = 'confirmed';
        CREATE UNIQUE INDEX onu_cpe_links_one_confirmed_per_cpe ON onu_cpe_links (tenant_id, cpe_id) WHERE status = 'confirmed';
        ALTER TABLE onu_cpe_links ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onu_cpe_links FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON onu_cpe_links USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON onu_cpe_links TO fibercore_app;
        GRANT UPDATE (status, reviewed_by, reviewed_at) ON onu_cpe_links TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS onu_cpe_links;")
