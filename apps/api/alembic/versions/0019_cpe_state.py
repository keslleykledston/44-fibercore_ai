"""Observed CPE state (WAN/Wi-Fi) delivered by the Edge from the ACS cache (SD-001, ADR-SD-002)

One row per (cpe, metric, scope): the LATEST observation. `captured_at` is the device-side timestamp the ACS kept (what the rules must
reason about); `observed_at` is the Edge round that carried it; `received_at` is the server clock. A closed list of metric names and a
digits-and-slashes scope keep free text (SSID, PSK, PPPoE user, MAC) out by construction; the Edge validates before sending and the API
validates again.

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE cpe_state (
          tenant_id uuid NOT NULL,
          cpe_id uuid NOT NULL,
          metric text NOT NULL CHECK (metric IN (
            'wan_link_status','wan_connection_status','uptime_seconds','wifi_radio_enabled','wifi_channel')),
          scope text NOT NULL CHECK (scope ~ '^[a-z]+(/[0-9]+)+$' AND length(scope) <= 32),
          value jsonb NOT NULL CHECK (jsonb_typeof(value) IN ('string','number','boolean')),
          captured_at timestamptz NOT NULL,
          observed_at timestamptz NOT NULL,
          received_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, cpe_id, metric, scope),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id) ON DELETE CASCADE
        );
        ALTER TABLE cpe_state ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cpe_state FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON cpe_state USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON cpe_state TO fibercore_app;
        GRANT UPDATE (value, captured_at, observed_at, received_at) ON cpe_state TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cpe_state;")
