"""tenants.demo (immutable) and olt_query_latest.source may be 'mock' (DEMO tenant only, written by the owner CLI `olt-board-mock`)

`tenants.demo` is set ONLY when the tenant is created (owner CLI `create-tenant --demo`) and can never change afterwards (a trigger refuses any UPDATE of it): the board mock
is for demo tenants and a name is not proof of anything. The screens label a 'mock' value as a demonstration; the CLI refuses any tenant that is not the demonstration tenant and never overwrites an inventory read from the equipment. Revision ID: 0043  Revises: 0042
"""
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenants ADD COLUMN demo boolean NOT NULL DEFAULT false;
        CREATE FUNCTION tenants_demo_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.demo IS DISTINCT FROM OLD.demo THEN RAISE EXCEPTION 'tenants.demo is immutable'; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER tenants_demo_immutable BEFORE UPDATE ON tenants FOR EACH ROW EXECUTE FUNCTION tenants_demo_immutable();
        """
    )
    op.execute("ALTER TABLE olt_query_latest DROP CONSTRAINT olt_query_latest_source_check; "
               "ALTER TABLE olt_query_latest ADD CONSTRAINT olt_query_latest_source_check CHECK (source IN ('job', 'routine', 'mock'));")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tenants_demo_immutable ON tenants; DROP FUNCTION IF EXISTS tenants_demo_immutable(); ALTER TABLE tenants DROP COLUMN IF EXISTS demo;")
    op.execute("DELETE FROM olt_query_latest WHERE source = 'mock'; ALTER TABLE olt_query_latest DROP CONSTRAINT olt_query_latest_source_check; "
               "ALTER TABLE olt_query_latest ADD CONSTRAINT olt_query_latest_source_check CHECK (source IN ('job', 'routine'));")
