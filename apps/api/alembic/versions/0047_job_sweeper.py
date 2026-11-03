"""Periodic job sweeper (closes the gap recorded in KNOWN_ISSUES "Job gate"/"Jobs (FC22-015)"): `app_sweep_jobs`

Until now the two reconciliations of a job the Edge went quiet about ran only inside that Edge's own `GET /v1/edge/jobs/next`: a job `DISPATCHED` and never reported becomes `EXPIRED`
(5 minutes past its own expiry), and a BENCH write `ACCEPTED/DEVICE_PENDING/VERIFYING` and never finished becomes `UNKNOWN` (30 minutes without news) with its target write-locked. If the Edge
never polled again, both stayed unwritten. This function does the same two steps for every tenant and every Edge, so a worker can run them on a clock.

* It is SECURITY DEFINER and only `fibercore_worker` may EXECUTE it: the worker role gets NO grant on `jobs` or `bench_targets`, only this one entry point.
* It can only move a job in the directions the opportunistic sweep already moves it (`DISPATCHED`→`EXPIRED`, a gated write in flight→`UNKNOWN`) and write-lock a bench target (the
  fail-safe direction). It never releases a lock: `bench-unlock` stays a person's act. The stale window cannot be shortened by the caller (floor of 30 minutes inside).
* To find the tenants with something in flight the owner needs to read the live rows across tenants: one SELECT policy for the OWNER role, limited to the in-flight states. The updates themselves
  still run under the normal `tenant_isolation` policy (the function sets the tenant for each one).
Reversible. Revision ID: 0047  Revises: 0046
"""
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          EXECUTE format($p$CREATE POLICY sweeper_scan ON jobs FOR SELECT TO %I
                              USING (status IN ('DISPATCHED','ACCEPTED','DEVICE_PENDING','VERIFYING'))$p$, current_user);
        END $$;

        CREATE FUNCTION app_sweep_jobs(p_gated text[], p_stale_secs integer) RETURNS TABLE (expired integer, unknown integer, locked integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE t uuid; a integer; b integer; c integer; d integer; stale integer := GREATEST(COALESCE(p_stale_secs, 0), 1800);
        BEGIN
          expired := 0; unknown := 0; locked := 0;
          FOR t IN SELECT DISTINCT tenant_id FROM jobs WHERE status IN ('DISPATCHED','ACCEPTED','DEVICE_PENDING','VERIFYING') LOOP
            PERFORM set_config('app.tenant_id', t::text, true);
            -- a dispatched job nobody reported: the envelope is long dead; a gated write that may have been applied locks its target
            WITH s AS (UPDATE jobs SET status = 'EXPIRED', updated_at = now()
                        WHERE status = 'DISPATCHED' AND expires_at < now() - interval '5 minutes' RETURNING operation, target_id),
                 l AS (UPDATE bench_targets bt SET write_locked = true, lock_reason = 'bench write dispatched and never reported'
                        FROM s WHERE bt.cpe_id = s.target_id AND s.operation = ANY(COALESCE(p_gated, ARRAY[]::text[])) AND NOT bt.write_locked RETURNING 1)
            SELECT (SELECT count(*) FROM s), (SELECT count(*) FROM l) INTO a, b;
            -- a gated write the Edge accepted and went quiet about: UNKNOWN (terminal) and its target locked until a person reconciles it
            WITH s AS (UPDATE jobs SET status = 'UNKNOWN', updated_at = now()
                        WHERE status IN ('ACCEPTED','DEVICE_PENDING','VERIFYING') AND operation = ANY(COALESCE(p_gated, ARRAY[]::text[]))
                          AND updated_at < now() - make_interval(secs => stale) RETURNING operation, target_id),
                 l AS (UPDATE bench_targets bt SET write_locked = true, lock_reason = 'bench write accepted and never finished'
                        FROM s WHERE bt.cpe_id = s.target_id AND NOT bt.write_locked RETURNING 1)
            SELECT (SELECT count(*) FROM s), (SELECT count(*) FROM l) INTO c, d;
            expired := expired + a; unknown := unknown + c; locked := locked + b + d;
          END LOOP;
          PERFORM set_config('app.tenant_id', '', true);
          RETURN NEXT;
        END $$;
        REVOKE ALL ON FUNCTION app_sweep_jobs(text[], integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_sweep_jobs(text[], integer) TO fibercore_worker;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_sweep_jobs(text[], integer); DROP POLICY IF EXISTS sweeper_scan ON jobs;")
