"""History of ONU state changes (`onu_state_events`): the base for "time offline in the month", drop counts and chronic offenders.

One row per REAL change of `onus.status` (and one baseline row per ONU: its first sighting, or its state when this migration ran). Written ONLY by a
trigger on `onus`, so it sees exactly the updates the ingest applied (a stale or replayed snapshot changes nothing, hence logs nothing) and the
application role has no way to forge or edit history: it can only read. The event time is the snapshot's observation, never later than the server clock.

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
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, onu_id) REFERENCES onus(tenant_id, id) ON DELETE CASCADE,
          CHECK (from_status IS DISTINCT FROM to_status)
        );
        CREATE INDEX onu_state_events_onu_idx ON onu_state_events (tenant_id, onu_id, at DESC, created_at DESC);
        CREATE INDEX onu_state_events_time_idx ON onu_state_events (tenant_id, at DESC);
        ALTER TABLE onu_state_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onu_state_events FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON onu_state_events USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON onu_state_events TO fibercore_app;   -- read only: history cannot be written or edited through the application role

        -- the baseline of every ONU that exists now (state as last known; an offline ONU starts at its known drop time when there is one)
        INSERT INTO onu_state_events (tenant_id, onu_id, olt_id, pon_id, serial, from_status, to_status, at)
          SELECT tenant_id, id, olt_id, pon_id, serial, NULL, status,
                 LEAST(COALESCE(CASE WHEN status IN ('offline','los','dying_gasp') THEN COALESCE(down_since, olt_down_at) END, observed_at, now()), now())
            FROM onus;

        CREATE FUNCTION onu_state_events_log() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            INSERT INTO onu_state_events (tenant_id, onu_id, olt_id, pon_id, serial, from_status, to_status, at)
              VALUES (NEW.tenant_id, NEW.id, NEW.olt_id, NEW.pon_id, NEW.serial, NULL, NEW.status, LEAST(COALESCE(NEW.observed_at, now()), now()));
          ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
            INSERT INTO onu_state_events (tenant_id, onu_id, olt_id, pon_id, serial, from_status, to_status, at)
              VALUES (NEW.tenant_id, NEW.id, NEW.olt_id, NEW.pon_id, NEW.serial, OLD.status, NEW.status, LEAST(COALESCE(NEW.observed_at, now()), now()));
          END IF;
          RETURN NULL;
        END $$;
        REVOKE ALL ON FUNCTION onu_state_events_log() FROM PUBLIC;
        CREATE TRIGGER onu_state_events_log AFTER INSERT OR UPDATE OF status ON onus FOR EACH ROW EXECUTE FUNCTION onu_state_events_log();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS onu_state_events_log ON onus; DROP FUNCTION IF EXISTS onu_state_events_log(); DROP TABLE IF EXISTS onu_state_events;")
