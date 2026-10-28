"""jobs, approvals (write gate state machine)

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

STATES = ("DRAFT", "PREVIEWED", "PENDING_APPROVAL", "APPROVED", "DISPATCHED", "ACCEPTED", "DEVICE_PENDING",
          "VERIFYING", "SUCCEEDED", "FAILED", "EXPIRED", "UNKNOWN", "CANCELLED")


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    states = ",".join(f"'{s}'" for s in STATES)
    op.execute(
        f"""
        CREATE TABLE jobs (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          edge_id uuid NOT NULL,
          target_type text NOT NULL CHECK (target_type IN ('olt','cpe')),
          target_id uuid NOT NULL,
          operation text NOT NULL,
          params jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          intent_hash char(64) NOT NULL,
          idempotency_key text NOT NULL,
          risk text NOT NULL CHECK (risk IN ('R0','R1','R2','R3')),
          required_approvals integer NOT NULL CHECK (required_approvals BETWEEN 0 AND 2),
          status text NOT NULL DEFAULT 'PREVIEWED' CHECK (status IN ({states})),
          requested_by uuid NOT NULL,
          nonce text,
          result jsonb,
          expires_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, idempotency_key),
          FOREIGN KEY (tenant_id, edge_id) REFERENCES edges(tenant_id, id)
        );
        CREATE INDEX jobs_edge_dispatch_idx ON jobs(tenant_id, edge_id, status) WHERE status = 'APPROVED';
        CREATE TABLE job_approvals (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          job_id uuid NOT NULL,
          approver_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, job_id, approver_id),
          FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id)
        );
        """
    )
    for t in ("jobs", "job_approvals"):
        op.execute(
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY; "
            f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});"
        )
    op.execute(
        """
        GRANT SELECT, INSERT ON jobs, job_approvals TO fibercore_app;
        GRANT UPDATE (status, nonce, result, expires_at, updated_at) ON jobs TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_approvals, jobs CASCADE")
