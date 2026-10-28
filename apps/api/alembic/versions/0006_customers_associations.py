"""customers, associations, csv import batches (LGPD: no plaintext document)

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLES = ["customers", "associations", "import_batches"]


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        """
        CREATE TABLE customers (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          erp_source text NOT NULL,
          erp_customer_id text NOT NULL,
          display_name text NOT NULL,
          document_hmac text,                -- HMAC-SHA256 of the normalised document; plaintext CPF/CNPJ is never stored
          document_last4 text,
          contract_status text NOT NULL DEFAULT 'unknown' CHECK (contract_status IN ('active','suspended','cancelled','unknown')),
          source_updated_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, erp_source, erp_customer_id)
        );
        CREATE TABLE import_batches (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          source text NOT NULL,
          actor_id uuid,
          rows_total integer NOT NULL,
          rows_accepted integer NOT NULL,
          rows_rejected integer NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id)
        );
        CREATE TABLE associations (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          onu_id uuid NOT NULL,
          cpe_id uuid,
          customer_id uuid NOT NULL,
          score numeric(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
          evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
          status text NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested','approved','rejected')),
          reviewed_by uuid,
          reviewed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, onu_id) REFERENCES onus(tenant_id, id),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id),
          FOREIGN KEY (tenant_id, customer_id) REFERENCES customers(tenant_id, id),
          CHECK ((status = 'suggested') = (reviewed_by IS NULL))
        );
        -- one live suggestion per (onu, customer); one APPROVED customer per ONU
        CREATE UNIQUE INDEX associations_pair_uq ON associations(tenant_id, onu_id, customer_id) WHERE status <> 'rejected';
        CREATE UNIQUE INDEX associations_one_approved_per_onu ON associations(tenant_id, onu_id) WHERE status = 'approved';
        """
    )
    for t in TABLES:
        op.execute(
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY; "
            f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});"
        )
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE ON customers TO fibercore_app;
        GRANT SELECT, INSERT ON import_batches TO fibercore_app;
        GRANT SELECT, INSERT ON associations TO fibercore_app;
        GRANT UPDATE (status, reviewed_by, reviewed_at) ON associations TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS associations, import_batches, customers CASCADE")
