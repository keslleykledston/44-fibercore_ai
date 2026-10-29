"""Per-tenant feature flags (ADR-0023): gradual release of v2.2 capabilities

A row overrides the code default for ONE tenant. The application role can only READ; flags are changed by the owner CLI
(`app.cli feature-set`), which validates the name against the code catalog and emits an event.

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE tenant_features (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          feature text NOT NULL CHECK (feature ~ '^[a-z][a-z0-9_]{{1,63}}$'),
          enabled boolean NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, feature)
        );
        ALTER TABLE tenant_features ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_features FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tenant_features USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON tenant_features TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_features;")
