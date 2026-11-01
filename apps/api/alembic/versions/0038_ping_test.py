"""Ping test TR-143 IPPing (ADR-0030 amendment line Q1, ADR-0039): logical ping destinations and one row per test run

`probe_targets` is the cloud's catalog of LOGICAL ping destinations: an id, a label, CORE or INTERNET, a region, enabled and the ONE Edge that owns the address.
It has no column for an address, a name or a credential, by construction: the Edge maps an id to the IP literal in its own local configuration, so nothing
here can point equipment at an arbitrary place. Only the owner CLI writes it.

`ping_test_runs` is one row per ping test (the job it rides on keeps the lifecycle). It holds who asked, which destination, and, once the Edge reported, the
figures the cloud COMPUTED from the device's raw leaves (counts, loss, min/avg/max times). No payload, no address. A figure exists only for a measurement.

The bench operation also becomes authorizable through the API by the engineering roles (ADR-0030 section 2(e) table), as the speed tests are.

Revision ID: 0038
Revises: 0037
"""
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE probe_targets (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id text NOT NULL CHECK (id ~ '^[a-z0-9][a-z0-9-]{{1,30}}$'),
          label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 60),
          target_kind text NOT NULL CHECK (target_kind IN ('CORE', 'INTERNET')),
          region text NOT NULL CHECK (region ~ '^[A-Za-z0-9 ._-]{{1,40}}$'),
          enabled boolean NOT NULL DEFAULT false,
          edge_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, edge_id) REFERENCES edges(tenant_id, id)
        );
        ALTER TABLE probe_targets ENABLE ROW LEVEL SECURITY;
        ALTER TABLE probe_targets FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON probe_targets USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON probe_targets TO fibercore_app;

        CREATE TABLE ping_test_runs (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          cpe_id uuid NOT NULL,
          job_id uuid NOT NULL,
          target_id text NOT NULL,
          requested_by uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          outcome text CHECK (outcome IN ('completed', 'inconclusive', 'error')),
          success_count integer CHECK (success_count BETWEEN 0 AND 10),
          failure_count integer CHECK (failure_count BETWEEN 0 AND 10),
          loss_pct numeric(5, 2) CHECK (loss_pct BETWEEN 0 AND 100),
          avg_ms integer CHECK (avg_ms >= 0),
          min_ms integer CHECK (min_ms >= 0),
          max_ms integer CHECK (max_ms >= 0),
          reason text CHECK (reason ~ '^[a-z_]{{1,40}}$'),
          completed_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, job_id),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id),
          FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id),
          FOREIGN KEY (tenant_id, target_id) REFERENCES probe_targets(tenant_id, id),
          CHECK ((outcome IS NULL) = (completed_at IS NULL)),
          -- counts and loss exist only for a finished test that reported them; times only when at least one reply came back; never a 0 standing for "no data"
          CHECK ((success_count IS NOT NULL) = (loss_pct IS NOT NULL)),
          CHECK ((success_count IS NOT NULL) = (failure_count IS NOT NULL)),
          CHECK (success_count IS NULL OR outcome = 'completed'),
          CHECK ((avg_ms IS NOT NULL) = (min_ms IS NOT NULL) AND (avg_ms IS NOT NULL) = (max_ms IS NOT NULL)),
          CHECK (avg_ms IS NULL OR (COALESCE(success_count, 0) > 0 AND min_ms <= avg_ms AND avg_ms <= max_ms))
        );
        CREATE INDEX ping_test_runs_cpe ON ping_test_runs (tenant_id, cpe_id, created_at DESC);
        ALTER TABLE ping_test_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ping_test_runs FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON ping_test_runs USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON ping_test_runs TO fibercore_app;
        GRANT UPDATE (outcome, success_count, failure_count, loss_pct, avg_ms, min_ms, max_ms, reason, completed_at) ON ping_test_runs TO fibercore_app;

        INSERT INTO rbac_bench_authorizers VALUES ('engineer', 'ping_test'), ('isp_admin', 'ping_test');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM rbac_bench_authorizers WHERE operation = 'ping_test';
        DROP TABLE IF EXISTS ping_test_runs;
        DROP TABLE IF EXISTS probe_targets;
        """
    )
