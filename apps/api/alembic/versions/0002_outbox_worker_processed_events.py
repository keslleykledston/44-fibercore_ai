"""least-privilege outbox relay role + idempotent consumer ledger

Revision ID: 0002
Revises: 0001
"""
import os
import re

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _pw() -> str:
    pw = os.environ.get("WORKER_DB_PASSWORD", "")
    if len(pw) < 16 or not re.fullmatch(r"[A-Za-z0-9_.\-]+", pw):
        raise RuntimeError("WORKER_DB_PASSWORD must be >=16 chars of [A-Za-z0-9_.-]")
    return pw


def upgrade() -> None:
    pw = _pw()
    op.execute(  # noqa: S608 - pw validated by regex above
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fibercore_worker') THEN
            CREATE ROLE fibercore_worker LOGIN;
          END IF;
        END $$;
        ALTER ROLE fibercore_worker LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{pw}';
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = 'fibercore_worker') THEN
            RAISE EXCEPTION 'fibercore_worker must not be a member of any role';
          END IF;
        END $$;
        """
    )
    # Relay may read unpublished events of all tenants and set published_at. Nothing else.
    op.execute(
        """
        GRANT USAGE ON SCHEMA public TO fibercore_worker;
        GRANT SELECT ON events_outbox TO fibercore_worker;
        GRANT UPDATE (published_at) ON events_outbox TO fibercore_worker;
        CREATE POLICY relay_read ON events_outbox FOR SELECT TO fibercore_worker USING (true);
        CREATE POLICY relay_mark ON events_outbox FOR UPDATE TO fibercore_worker USING (true) WITH CHECK (true);
        -- the app role must not touch published_at semantics beyond its own tenant: keep as in 0001.
        """
    )
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE processed_events (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          consumer text NOT NULL,
          event_id uuid NOT NULL,
          processed_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, consumer, event_id)
        );
        ALTER TABLE processed_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE processed_events FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON processed_events
          USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON processed_events TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS processed_events")
    op.execute("DROP POLICY IF EXISTS relay_read ON events_outbox; DROP POLICY IF EXISTS relay_mark ON events_outbox")
    op.execute("REVOKE ALL ON events_outbox FROM fibercore_worker")
