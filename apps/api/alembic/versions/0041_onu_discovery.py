"""ONU discovery observations (v2.5, FC25-01/02/03): serials seen waiting for authorisation on an OLT/PON

`onu_discovery_observations` keeps what was OBSERVED, per (tenant, OLT, PON, serial, source): first/last seen and a counter. The source is part of the key so a manual
import or a fixture can never refresh (or be confused with) what the Edge read from the OLT. The application role can SELECT, INSERT and UPDATE only the sighting columns;
there is no DELETE. Nothing here authorises an ONU or writes to equipment. The feature `onu_discovery` is OFF by default (code catalog).

Revision ID: 0041
Revises: 0040
"""
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE onu_discovery_observations (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          olt_id uuid NOT NULL,
          pon_path text NOT NULL CHECK (pon_path ~ '^[0-9]{{1,3}}(/[0-9]{{1,3}}){{1,3}}$'),
          serial text NOT NULL CHECK (serial ~ '^[A-Z0-9]{{4,32}}$'),
          vendor_hint text CHECK (vendor_hint IS NULL OR char_length(vendor_hint) BETWEEN 1 AND 40),
          source text NOT NULL CHECK (source IN ('fixture', 'manual_import', 'edge_read')),
          first_seen_at timestamptz NOT NULL,
          last_seen_at timestamptz NOT NULL,
          seen_count integer NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
          created_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, olt_id, pon_path, serial, source),
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id),
          CHECK (last_seen_at >= first_seen_at)
        );
        CREATE INDEX onu_discovery_by_olt ON onu_discovery_observations (tenant_id, olt_id, last_seen_at DESC);
        CREATE INDEX onu_discovery_by_serial ON onu_discovery_observations (tenant_id, serial);
        -- the queue asks "is this serial already a registered ONU?" with upper(serial): the lookup must be indexable
        CREATE INDEX onus_tenant_upper_serial ON onus (tenant_id, upper(serial));
        ALTER TABLE onu_discovery_observations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onu_discovery_observations FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON onu_discovery_observations USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON onu_discovery_observations TO fibercore_app;
        GRANT UPDATE (last_seen_at, seen_count, vendor_hint) ON onu_discovery_observations TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS onu_discovery_observations; DROP INDEX IF EXISTS onus_tenant_upper_serial;")
