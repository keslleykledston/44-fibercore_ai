"""History of ONU state changes (`onu_state_events`): the base for "time offline in the month", drop counts and chronic offenders.

One row per REAL change of `onus.status` (and one baseline row per ONU: its first sighting, or its state when this migration ran). Written ONLY by a
trigger on `onus`, so it sees exactly the updates the ingest applied (a stale or replayed snapshot changes nothing, hence logs nothing) and the
application role has no way to forge or edit history: it can only read. The event time is the snapshot's observation, never later than the server clock
and never earlier than the previous event of the same ONU; the order of events is the persisted ordinal `seq` (assigned under the ONU's row lock), not a
timestamp, so equal times cannot be reordered. The baseline of ONUs that already exist is the instant of this migration: nothing before it was observed.

Revision ID: 0028
Revises: 0027
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE onu_state_events (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          onu_id uuid NOT NULL,
          olt_id uuid NOT NULL,
          pon_id uuid,
          serial text NOT NULL,
          from_status text CHECK (from_status IS NULL OR from_status IN ('online','offline','los','dying_gasp','unknown')),
          to_status text NOT NULL CHECK (to_status IN ('online','offline','los','dying_gasp','unknown')),
          at timestamptz NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          seq bigint GENERATED ALWAYS AS IDENTITY,
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, onu_id) REFERENCES onus(tenant_id, id) ON DELETE CASCADE,
          CHECK (from_status IS DISTINCT FROM to_status)
        );
        CREATE UNIQUE INDEX onu_state_events_seq_idx ON onu_state_events (seq);
        CREATE INDEX onu_state_events_onu_idx ON onu_state_events (tenant_id, onu_id, seq DESC);
        CREATE INDEX onu_state_events_time_idx ON onu_state_events (tenant_id, at DESC);
        ALTER TABLE onu_state_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onu_state_events FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON onu_state_events USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON onu_state_events TO fibercore_app;   -- read only: history cannot be written or edited through the application role

        -- the baseline of every ONU that exists now: its state as last known, starting when this trail began (a known `down_since` stays on the ONU itself)
        INSERT INTO onu_state_events (tenant_id, onu_id, olt_id, pon_id, serial, from_status, to_status, at)
          SELECT tenant_id, id, olt_id, pon_id, serial, NULL, status, now() FROM onus;

        CREATE FUNCTION onu_state_events_log() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE prev timestamptz; t timestamptz;
        BEGIN
          IF TG_OP = 'UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status THEN RETURN NULL; END IF;
          -- the UPDATE holds the ONU's row lock, so concurrent changes of one ONU are serialised here and `seq` follows the order they were applied
          SELECT at INTO prev FROM onu_state_events WHERE tenant_id = NEW.tenant_id AND onu_id = NEW.id ORDER BY seq DESC LIMIT 1;
          t := GREATEST(LEAST(COALESCE(NEW.observed_at, now()), now()), COALESCE(prev, '-infinity'::timestamptz));
          INSERT INTO onu_state_events (tenant_id, onu_id, olt_id, pon_id, serial, from_status, to_status, at)
            VALUES (NEW.tenant_id, NEW.id, NEW.olt_id, NEW.pon_id, NEW.serial, CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.status END, NEW.status, t);
          RETURN NULL;
        END $$;
        REVOKE ALL ON FUNCTION onu_state_events_log() FROM PUBLIC;
        CREATE TRIGGER onu_state_events_log AFTER INSERT OR UPDATE OF status ON onus FOR EACH ROW EXECUTE FUNCTION onu_state_events_log();

        -- retention: events older than `keep_days` go, except the last one before the cut-off of each ONU (it carries the state the window starts in).
        -- Not executable by the application role: it runs from the host (see docs/ops), like the backups.
        CREATE FUNCTION onu_state_events_prune(keep_days int) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE n bigint;
        BEGIN
          IF keep_days IS NULL OR keep_days < 370 THEN RAISE EXCEPTION 'keep_days must cover the longest query window (365 days)'; END IF;
          WITH keep AS (SELECT DISTINCT ON (tenant_id, onu_id) seq FROM onu_state_events WHERE at < now() - make_interval(days => keep_days)
                         ORDER BY tenant_id, onu_id, seq DESC)
          DELETE FROM onu_state_events e WHERE e.at < now() - make_interval(days => keep_days) AND NOT EXISTS (SELECT 1 FROM keep k WHERE k.seq = e.seq);
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END $$;
        REVOKE ALL ON FUNCTION onu_state_events_prune(int) FROM PUBLIC;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS onu_state_events_log ON onus; DROP FUNCTION IF EXISTS onu_state_events_log(); DROP FUNCTION IF EXISTS onu_state_events_prune(int); DROP TABLE IF EXISTS onu_state_events;")
