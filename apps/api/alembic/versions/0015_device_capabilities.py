"""Capability Registry: what is known about an operation on a vendor/model/firmware profile (ADR-0019, FC22-002)

Per tenant (RLS forced). A profile with no row is UNKNOWN/identified: the absence of evidence is never support. The application role can only
READ; rows are written by the owner CLI (`app.cli capability-set`), which demands evidence for `observed`/`certified`.

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE device_capabilities (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          vendor text NOT NULL CHECK (vendor = btrim(vendor) AND vendor <> ''),
          model text NOT NULL CHECK (model = btrim(model) AND model <> ''),
          firmware text NOT NULL CHECK (firmware = btrim(firmware) AND firmware <> ''),
          protocol text NOT NULL CHECK (protocol IN ('tr069','tr369','olt')),
          operation text NOT NULL CHECK (operation ~ '^[a-z][a-z0-9_.]{{1,63}}$'),
          status text NOT NULL DEFAULT 'unknown' CHECK (status IN ('supported','unsupported','unknown')),
          certification text NOT NULL DEFAULT 'identified' CHECK (certification IN ('identified','observed','certified')),
          verified_at timestamptz,
          evidence_ref text CHECK (evidence_ref IS NULL OR (length(evidence_ref) <= 300 AND evidence_ref !~ '[[:cntrl:]]')),
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          -- observed/certified are claims about the real world: they must point at evidence and say when it was verified
          CHECK (certification = 'identified' OR (evidence_ref IS NOT NULL AND verified_at IS NOT NULL)),
          -- and so is "supported"/"unsupported": without evidence the only honest status is unknown
          CHECK (status = 'unknown' OR (evidence_ref IS NOT NULL AND verified_at IS NOT NULL))
        );
        CREATE UNIQUE INDEX device_capabilities_profile_op
          ON device_capabilities (tenant_id, lower(vendor), lower(model), firmware, protocol, operation);
        ALTER TABLE device_capabilities ENABLE ROW LEVEL SECURITY;
        ALTER TABLE device_capabilities FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON device_capabilities USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON device_capabilities TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS device_capabilities;")
