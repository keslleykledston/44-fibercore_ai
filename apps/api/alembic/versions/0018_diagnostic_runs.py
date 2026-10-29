"""Diagnostic runs: append-only record of deterministic rule executions (FC22-006)

A run stores the rule id + VERSION, the exact inputs it was given and the findings it produced, so anyone can re-evaluate the stored inputs
under the same version and get the same findings. The application role can only INSERT and SELECT: a run is never edited or deleted.

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE diagnostic_runs (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          rule_id text NOT NULL CHECK (rule_id ~ '^R-D[0-9]{{3}}$'),
          rule_version integer NOT NULL CHECK (rule_version >= 1),
          scope jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          inputs jsonb NOT NULL CHECK (jsonb_typeof(inputs) = 'array'),
          findings jsonb NOT NULL CHECK (jsonb_typeof(findings) = 'array'),
          truncated boolean NOT NULL DEFAULT false,
          requested_by uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id)
        );
        CREATE INDEX diagnostic_runs_recent_idx ON diagnostic_runs (tenant_id, created_at DESC);
        ALTER TABLE diagnostic_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE diagnostic_runs FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON diagnostic_runs USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON diagnostic_runs TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS diagnostic_runs;")
