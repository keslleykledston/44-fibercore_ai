"""Diagnostic jobs: passive, read-only, customer-centred diagnostics with evidence (SD-001, ADR-0025/ADR-0028)

One immutable row per job (the app can only INSERT/SELECT): the request, the evidence the job gathered from data we already hold, the rule
runs it evaluated (rule id + version + exact inputs, so the result can be replayed) and the findings. Evidence and findings are validated
against contracts/sd001 by the tests. No customer name/document/serial is stored: only ids and enum words.

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE diagnostic_jobs (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          requested_by uuid NOT NULL,
          idempotency_key text NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9_.-]{{8,128}}$'),
          request_hash text NOT NULL,
          request jsonb NOT NULL,
          mode text NOT NULL CHECK (mode = 'passive'),
          status text NOT NULL CHECK (status IN ('complete','partial','inconclusive','failed')),
          data_quality text NOT NULL CHECK (data_quality IN ('fresh','partial','stale','unsupported')),
          evidences jsonb NOT NULL CHECK (jsonb_typeof(evidences) = 'array'),
          findings jsonb NOT NULL CHECK (jsonb_typeof(findings) = 'array'),
          rule_runs jsonb NOT NULL CHECK (jsonb_typeof(rule_runs) = 'array'),
          created_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, requested_by, idempotency_key)
        );
        CREATE INDEX diagnostic_jobs_recent_idx ON diagnostic_jobs (tenant_id, created_at DESC);
        ALTER TABLE diagnostic_jobs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE diagnostic_jobs FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON diagnostic_jobs USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON diagnostic_jobs TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS diagnostic_jobs;")
