"""QoS-001 (ADR-0039): one immutable row per quality read of an ONT

`quality_runs` is the SUITE record: the mode, the state, the normalized metrics (value, unit, source, scope, instance, collected_at, freshness, status), the
hypotheses with their evidence, the summary, and REFERENCES to the SD-001 runs of a complete read (their group id), never copies of them. Rows are only
inserted and read (the application role has no UPDATE or DELETE), RLS is forced, and a retry with the same Idempotency-Key returns the same run. No address,
SSID, MAC or serial is stored: the metrics carry only closed ids, enum words, numbers and timestamps.

Revision ID: 0037
Revises: 0036
"""
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE quality_runs (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          cpe_id uuid NOT NULL,
          mode text NOT NULL CHECK (mode IN ('quick', 'full')),
          state text NOT NULL CHECK (state IN ('completed', 'partial', 'failed', 'timeout')),
          requested_by uuid NOT NULL,
          idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 8 AND 128),
          schema_version integer NOT NULL DEFAULT 1,
          metrics jsonb NOT NULL,
          hypotheses jsonb NOT NULL DEFAULT '[]'::jsonb,
          summary jsonb NOT NULL,
          speed_group_ids uuid[] NOT NULL DEFAULT '{{}}',
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id),
          UNIQUE (tenant_id, requested_by, idempotency_key)
        );
        CREATE INDEX quality_runs_cpe_idx ON quality_runs (tenant_id, cpe_id, created_at DESC);
        ALTER TABLE quality_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE quality_runs FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON quality_runs USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON quality_runs TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS quality_runs;")
