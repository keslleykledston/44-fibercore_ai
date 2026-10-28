"""inventory domain: olts, pon_ports, onus, cpes, cpe_protocol_bindings (+RLS, grants)

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLES = ["olts", "pon_ports", "onus", "cpes", "cpe_protocol_bindings"]


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        """
        CREATE TABLE olts (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          edge_id uuid NOT NULL,
          name text NOT NULL,
          vendor text NOT NULL,
          model text,
          firmware text,
          credential_secret_ref text,           -- reference only, NEVER the secret
          support_level text NOT NULL DEFAULT 'identified' CHECK (support_level IN ('identified','observed','certified')),
          observed_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, name),
          FOREIGN KEY (tenant_id, edge_id) REFERENCES edges(tenant_id, id)
        );
        CREATE TABLE pon_ports (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          olt_id uuid NOT NULL,
          pon_path text NOT NULL,
          status text NOT NULL DEFAULT 'unknown' CHECK (status IN ('up','down','unknown')),
          observed_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, olt_id, pon_path),
          UNIQUE (tenant_id, olt_id, id),   -- target of onus composite FK (PON must belong to the ONU's OLT)
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id) ON DELETE CASCADE
        );
        CREATE TABLE onus (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          olt_id uuid NOT NULL,
          pon_id uuid,
          serial text NOT NULL,
          status text NOT NULL DEFAULT 'unknown' CHECK (status IN ('online','offline','los','dying_gasp','unknown')),
          rx_dbm numeric(7,2) CHECK (rx_dbm BETWEEN -50 AND 10),
          observed_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, olt_id, serial),
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id) ON DELETE CASCADE,
          FOREIGN KEY (tenant_id, olt_id, pon_id) REFERENCES pon_ports(tenant_id, olt_id, id)
        );
        CREATE INDEX onus_tenant_serial_idx ON onus(tenant_id, serial);
        CREATE INDEX onus_tenant_olt_idx ON onus(tenant_id, olt_id);
        CREATE TABLE cpes (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          edge_id uuid NOT NULL,                -- owning edge: another edge cannot overwrite this CPE
          canonical_serial text NOT NULL,
          vendor text,
          model text,
          firmware text,
          observed_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, canonical_serial),
          FOREIGN KEY (tenant_id, edge_id) REFERENCES edges(tenant_id, id)
        );
        CREATE TABLE cpe_protocol_bindings (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          cpe_id uuid NOT NULL,
          protocol text NOT NULL CHECK (protocol IN ('tr069','tr369')),
          external_id text NOT NULL,
          connector_id text NOT NULL,
          observed_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, connector_id, protocol, external_id),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id) ON DELETE CASCADE
        );
        """
    )
    for t in TABLES:
        op.execute(
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY; "
            f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t}); "
            f"GRANT SELECT, INSERT, UPDATE ON {t} TO fibercore_app;"
        )
    # No DELETE for runtime: inventory removal is an explicit owner/ops action (history + audit), not an Edge side effect.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cpe_protocol_bindings, cpes, onus, pon_ports, olts CASCADE")
