"""Speed Diagnostics TR-143 (ADR-0038): logical test endpoints and one row per test run

`speed_endpoints` is the cloud's catalog of LOGICAL destinations: an id, a label, CORE or INTERNET, a region, enabled and the last health the Edge reported. It has
no column for a URL, an address, a token or a credential, by construction: the Edge maps an id to its own local address, so nothing here can be used to point
equipment at an arbitrary place. Only the owner CLI writes it.

`speed_test_runs` is one row per direction of a test (the job it rides on keeps the lifecycle). It holds who asked, which endpoint and profile, the PON the
limit was counted on, and, once the Edge reported, the figures the cloud COMPUTED from raw counters. No payload, no raw counter, no address.

The two bench operations also become authorizable through the API by the engineering roles (ADR-0030 section 2(e) table), as the OLT-side maneuvers are.

Revision ID: 0034
Revises: 0033
"""
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE speed_endpoints (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id text NOT NULL CHECK (id ~ '^[a-z0-9][a-z0-9-]{{1,30}}$'),
          label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 60),
          target_kind text NOT NULL CHECK (target_kind IN ('CORE', 'INTERNET')),
          region text NOT NULL CHECK (region ~ '^[A-Za-z0-9 ._-]{{1,40}}$'),
          enabled boolean NOT NULL DEFAULT false,
          health text NOT NULL DEFAULT 'unknown' CHECK (health IN ('unknown', 'ok', 'degraded', 'down')),
          health_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id)
        );
        ALTER TABLE speed_endpoints ENABLE ROW LEVEL SECURITY;
        ALTER TABLE speed_endpoints FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON speed_endpoints USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON speed_endpoints TO fibercore_app;

        CREATE TABLE speed_test_runs (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          cpe_id uuid NOT NULL,
          job_id uuid NOT NULL,
          group_id uuid NOT NULL,
          direction text NOT NULL CHECK (direction IN ('download', 'upload')),
          endpoint_id text NOT NULL,
          profile text NOT NULL CHECK (profile IN ('10mb', '50mb', '200mb')),
          pon_id uuid NOT NULL,
          requested_by uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          outcome text CHECK (outcome IN ('completed', 'partial', 'inconclusive', 'error')),
          mbps numeric(10, 2) CHECK (mbps > 0),
          bytes bigint CHECK (bytes > 0),
          duration_ms integer CHECK (duration_ms > 0),
          reason text CHECK (reason ~ '^[a-z_]{{1,40}}$'),
          basis text CHECK (basis IN ('test_bytes_received', 'test_bytes_sent', 'test_file_length')),
          completed_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, job_id),
          UNIQUE (tenant_id, group_id, direction),   -- a group is one test: one run per direction
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id),
          FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id),
          FOREIGN KEY (tenant_id, endpoint_id) REFERENCES speed_endpoints(tenant_id, id),
          -- a figure exists only for a measurement, and a measurement only after the outcome is recorded: never a 0, never a number without its counters
          CHECK ((mbps IS NOT NULL) = COALESCE(outcome IN ('completed', 'partial'), false)),   -- NULL outcome = no figure
          CHECK ((outcome IS NULL) = (completed_at IS NULL))
        );
        CREATE INDEX speed_test_runs_cpe ON speed_test_runs (tenant_id, cpe_id, created_at DESC);
        CREATE INDEX speed_test_runs_pon ON speed_test_runs (tenant_id, pon_id);
        ALTER TABLE speed_test_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE speed_test_runs FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON speed_test_runs USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON speed_test_runs TO fibercore_app;
        GRANT UPDATE (outcome, mbps, bytes, duration_ms, reason, basis, completed_at) ON speed_test_runs TO fibercore_app;

        INSERT INTO rbac_bench_authorizers VALUES
          ('engineer', 'speed_test_download'), ('engineer', 'speed_test_upload'),
          ('isp_admin', 'speed_test_download'), ('isp_admin', 'speed_test_upload');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM rbac_bench_authorizers WHERE operation IN ('speed_test_download', 'speed_test_upload');
        DROP TABLE IF EXISTS speed_test_runs;
        DROP TABLE IF EXISTS speed_endpoints;
        """
    )
