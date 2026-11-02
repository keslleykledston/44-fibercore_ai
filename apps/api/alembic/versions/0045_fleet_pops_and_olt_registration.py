"""Fleet Manager (ADR-0041, PR2 part A): POPs and the registration fields of an OLT

`pops` names the physical sites of the provider (a name, an optional short code and note: no addresses of customers, no coordinates of equipment). `olts` gains the POP link,
a human label and who/when registered it; the credential stays where it always was: `olts.credential_secret_ref` is a NAME that the Edge resolves in its own local secret store
(this migration only constrains its shape: a name, never an address nor a secret). The application role may INSERT/UPDATE only the new registration columns, never the ownership
ones (owner_epoch, edge change stay owner-only, ADR-0029). Reversible: the downgrade drops the new columns and the table. Revision ID: 0045  Revises: 0044
"""
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE pops (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          name text NOT NULL CHECK (char_length(name) BETWEEN 2 AND 60),
          code text CHECK (code IS NULL OR code ~ '^[A-Za-z0-9][A-Za-z0-9_-]{{0,23}}$'),
          note text CHECK (note IS NULL OR char_length(note) <= 200),
          created_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id)
        );
        CREATE UNIQUE INDEX pops_name_ci ON pops (tenant_id, lower(name));
        ALTER TABLE pops ENABLE ROW LEVEL SECURITY;
        ALTER TABLE pops FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON pops USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON pops TO fibercore_app;
        GRANT UPDATE (name, code, note) ON pops TO fibercore_app;

        ALTER TABLE olts
          ADD COLUMN pop_id uuid,
          ADD COLUMN label text CHECK (label IS NULL OR char_length(label) BETWEEN 1 AND 80),
          ADD COLUMN registered_by uuid,
          ADD COLUMN registered_at timestamptz,
          ADD CONSTRAINT olts_pop FOREIGN KEY (tenant_id, pop_id) REFERENCES pops(tenant_id, id),
          ADD CONSTRAINT olts_credential_ref_shape CHECK (credential_secret_ref IS NULL OR (credential_secret_ref ~ '^[a-z0-9][a-z0-9_.-]{{0,63}}$'
            AND credential_secret_ref !~ '^[0-9]{{1,3}}(\\.[0-9]{{1,3}}){{3}}$' AND credential_secret_ref !~ '^[0-9a-f]{{32,}}$')) NOT VALID;
        GRANT INSERT (pop_id, label, registered_by, registered_at, credential_secret_ref) ON olts TO fibercore_app;
        GRANT UPDATE (pop_id, label, credential_secret_ref) ON olts TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE INSERT (pop_id, label, registered_by, registered_at, credential_secret_ref) ON olts FROM fibercore_app;
        REVOKE UPDATE (pop_id, label, credential_secret_ref) ON olts FROM fibercore_app;
        ALTER TABLE olts DROP CONSTRAINT IF EXISTS olts_credential_ref_shape, DROP CONSTRAINT IF EXISTS olts_pop,
          DROP COLUMN IF EXISTS registered_at, DROP COLUMN IF EXISTS registered_by, DROP COLUMN IF EXISTS label, DROP COLUMN IF EXISTS pop_id;
        DROP TABLE IF EXISTS pops;
        """
    )
