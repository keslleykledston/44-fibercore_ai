"""Bench gate (ADR-0030): the closed list of bench targets, single-use prior authorizations and the job fields that bind to them

`bench_targets` and `bench_authorizations` are written ONLY by the owner CLI (the app role can read them; it can update just the write lock
on a target and consume an open authorization). Nothing here opens a write by itself: the job engine still needs the tenant flag, the
capability registry entry, the Edge-side configuration and the signed envelope (ADR-0030 item 5).

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE bench_targets (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          cpe_id uuid NOT NULL,
          edge_id uuid NOT NULL,
          owner_epoch integer NOT NULL DEFAULT 1 CHECK (owner_epoch >= 1),
          write_locked boolean NOT NULL DEFAULT false,
          lock_reason text CHECK (lock_reason IS NULL OR (length(lock_reason) <= 300 AND lock_reason !~ '[[:cntrl:]]')),
          note text CHECK (note IS NULL OR length(note) <= 300),
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, cpe_id),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id),
          CHECK (write_locked = (lock_reason IS NOT NULL))
        );
        CREATE TABLE bench_authorizations (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          operation text NOT NULL CHECK (operation ~ '^[a-z][a-z0-9_.]{{1,63}}$'),
          cpe_id uuid NOT NULL,
          params_hash text NOT NULL CHECK (params_hash ~ '^[0-9a-f]{{64}}$'),
          window_start timestamptz NOT NULL,
          window_end timestamptz NOT NULL,
          authorized_by text NOT NULL CHECK (authorized_by = btrim(authorized_by) AND authorized_by <> '' AND length(authorized_by) <= 100),
          state text NOT NULL DEFAULT 'open' CHECK (state IN ('open','consumed')),
          job_id uuid UNIQUE,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES bench_targets(tenant_id, cpe_id),
          CHECK (window_end > window_start AND window_end - window_start <= interval '4 hours'),
          CHECK ((state = 'consumed') = (job_id IS NOT NULL))
        );
        ALTER TABLE jobs ADD COLUMN authorization_id uuid, ADD COLUMN owner_epoch integer;
        CREATE UNIQUE INDEX jobs_one_per_authorization ON jobs (authorization_id) WHERE authorization_id IS NOT NULL;
        ALTER TABLE bench_targets ENABLE ROW LEVEL SECURITY;
        ALTER TABLE bench_targets FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON bench_targets USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        ALTER TABLE bench_authorizations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE bench_authorizations FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON bench_authorizations USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON bench_targets, bench_authorizations TO fibercore_app;
        GRANT UPDATE (write_locked, lock_reason) ON bench_targets TO fibercore_app;
        GRANT UPDATE (state, job_id) ON bench_authorizations TO fibercore_app;
        GRANT UPDATE (authorization_id, owner_epoch) ON jobs TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS jobs_one_per_authorization; ALTER TABLE jobs DROP COLUMN IF EXISTS authorization_id, DROP COLUMN IF EXISTS owner_epoch;"
               " DROP TABLE IF EXISTS bench_authorizations; DROP TABLE IF EXISTS bench_targets;")
