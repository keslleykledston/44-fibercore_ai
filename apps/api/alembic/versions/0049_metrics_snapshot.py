"""Operational metrics snapshot (ADR-0043): `app_metrics_snapshot()`

The Prometheus exporter (`app/workers/metrics_exporter.py`) must read AGGREGATES across tenants (Edges silent, outbox backlog, jobs by state, OLT collection age), and the tables are
under FORCE ROW LEVEL SECURITY. Same pattern as the job sweeper (0047): the worker role gets NO grant on any of those tables, only this one entry point.

* SECURITY DEFINER, STABLE, read-only: it can neither write nor return a row of anything. The result is ONE jsonb object of counts, ages in seconds and a map state -> count.
  No tenant id, user, Edge or OLT identifier, name, address, serial or payload is ever selected into it (a test checks the shape and that no UUID/IP appears).
* Only `fibercore_worker` may EXECUTE it (REVOKE from PUBLIC; the app/rbac roles cannot call it).
* The owner needs SELECT across tenants on the four tables it aggregates: one SELECT-only policy per table for the OWNER role (`metrics_scan`), exactly as 0047 did for `jobs`.
* Terminal job states are counted over the last 24 h only (the table is never pruned; an all-time count would only grow). The in-flight states are always counted.
Reversible. Revision ID: 0049  Revises: 0048
"""
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

IN_FLIGHT = ("DISPATCHED", "ACCEPTED", "DEVICE_PENDING", "VERIFYING")
TABLES = ("edges", "olts", "jobs", "events_outbox")


def upgrade() -> None:
    live = ", ".join(f"'{s}'" for s in IN_FLIGHT)
    policies = "\n".join(f"          EXECUTE format($p$CREATE POLICY metrics_scan ON {t} FOR SELECT TO %I USING (true)$p$, current_user);" for t in TABLES)
    op.execute(
        f"""
        DO $$ BEGIN
{policies}
        END $$;

        CREATE FUNCTION app_metrics_snapshot() RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT jsonb_build_object(
            'edges_active', (SELECT count(*) FROM edges WHERE status <> 'revoked'),
            'edges_never_heartbeat', (SELECT count(*) FROM edges WHERE status <> 'revoked' AND last_heartbeat_at IS NULL),
            'edge_heartbeat_age_seconds_max', (SELECT max(extract(epoch FROM now() - last_heartbeat_at)) FROM edges WHERE status <> 'revoked' AND last_heartbeat_at IS NOT NULL),
            'olts_registered', (SELECT count(*) FROM olts o JOIN edges e ON e.tenant_id = o.tenant_id AND e.id = o.edge_id WHERE e.status <> 'revoked'),
            'olts_never_collected', (SELECT count(*) FROM olts o JOIN edges e ON e.tenant_id = o.tenant_id AND e.id = o.edge_id WHERE e.status <> 'revoked' AND o.observed_at IS NULL),
            'olt_collection_age_seconds_max', (SELECT max(extract(epoch FROM now() - o.observed_at)) FROM olts o JOIN edges e ON e.tenant_id = o.tenant_id AND e.id = o.edge_id
                                               WHERE e.status <> 'revoked' AND o.observed_at IS NOT NULL),
            'outbox_unpublished', (SELECT count(*) FROM events_outbox WHERE published_at IS NULL),
            'outbox_oldest_unpublished_age_seconds', (SELECT max(extract(epoch FROM now() - created_at)) FROM events_outbox WHERE published_at IS NULL),
            'jobs', (SELECT COALESCE(jsonb_object_agg(status, n), '{{}}'::jsonb)
                       FROM (SELECT status, count(*) AS n FROM jobs WHERE status IN ({live}) OR updated_at > now() - interval '24 hours' GROUP BY status) s),
            'jobs_in_flight_oldest_age_seconds', (SELECT max(extract(epoch FROM now() - updated_at)) FROM jobs WHERE status IN ({live}))
          )
        $$;
        REVOKE ALL ON FUNCTION app_metrics_snapshot() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_metrics_snapshot() TO fibercore_worker;
        """
    )


def downgrade() -> None:
    drops = " ".join(f"DROP POLICY IF EXISTS metrics_scan ON {t};" for t in TABLES)
    op.execute(f"DROP FUNCTION IF EXISTS app_metrics_snapshot(); {drops}")
