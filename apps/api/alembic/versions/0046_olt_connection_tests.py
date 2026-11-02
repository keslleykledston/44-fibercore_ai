"""Fleet Manager (ADR-0041, PR2 part B): the history of OLT connection tests, the base of their per-OLT budget

One row per request that actually reached the budget logic: `submitted` (a job `olt_query/olt.connection` was created; counted against the budget: at most ONE per OLT every 15 minutes and FOUR
per hour, approved by the owner on 2026-11-02) or `cached` (a fresh stored identity answered; it spends nothing and never touches the equipment). The application role can only SELECT and INSERT: a
row is never edited or removed, so the budget cannot be reset from the application. Reversible. Revision ID: 0046  Revises: 0045
"""
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE olt_connection_tests (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          olt_id uuid NOT NULL,
          job_id uuid,
          outcome text NOT NULL CHECK (outcome IN ('submitted', 'cached')),
          requested_by uuid,
          requested_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id) ON DELETE CASCADE,
          CHECK ((outcome = 'submitted') = (job_id IS NOT NULL))
        );
        CREATE INDEX olt_connection_tests_olt ON olt_connection_tests (tenant_id, olt_id, requested_at DESC);
        ALTER TABLE olt_connection_tests ENABLE ROW LEVEL SECURITY;
        ALTER TABLE olt_connection_tests FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON olt_connection_tests USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON olt_connection_tests TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS olt_connection_tests;")
