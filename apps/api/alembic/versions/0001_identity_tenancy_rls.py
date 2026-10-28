"""identity, tenancy, audit, outbox + RLS

Revision ID: 0001
Revises:
"""
import os
import re

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = ["tenant_memberships", "service_accounts", "audit_log", "events_outbox"]

ROLES = "('isp_admin','engineer','noc_n2','noc_n1','support','auditor','platform_support')"


def _app_password() -> str:
    pw = os.environ.get("APP_DB_PASSWORD", "")
    if len(pw) < 16 or not re.fullmatch(r"[A-Za-z0-9_.\-]+", pw):
        raise RuntimeError("APP_DB_PASSWORD must be >=16 chars of [A-Za-z0-9_.-]")
    return pw


def upgrade() -> None:
    pw = _app_password()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # Runtime role: non-owner, no superuser, no BYPASSRLS. Idempotent.
    op.execute(  # noqa: S608 - pw validated by regex above
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fibercore_app') THEN
            CREATE ROLE fibercore_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
          END IF;
        END $$;
        ALTER ROLE fibercore_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{pw}';
        """
    )
    # Pre-existing role may carry inherited privileges: refuse rather than assume.
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member
                     WHERE r.rolname = 'fibercore_app') THEN
            RAISE EXCEPTION 'fibercore_app must not be a member of any role';
          END IF;
          IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
                     WHERE r.rolname = 'fibercore_app') THEN
            RAISE EXCEPTION 'fibercore_app must not own any relation';
          END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE tenants (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          name text NOT NULL,
          status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE users_global (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          email text UNIQUE NOT NULL,
          oidc_subject text UNIQUE,
          display_name text NOT NULL,
          password_hash text,
          is_active boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        f"""
        CREATE TABLE tenant_memberships (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          user_id uuid NOT NULL REFERENCES users_global(id),
          role text NOT NULL CHECK (role IN {ROLES}),
          PRIMARY KEY (tenant_id, user_id)
        );
        CREATE TABLE service_accounts (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          name text NOT NULL,
          role text NOT NULL CHECK (role IN {ROLES}),
          secret_hash text NOT NULL,
          is_active boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (id),
          UNIQUE (tenant_id, name)
        );
        CREATE TABLE audit_log (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          actor_id uuid,
          action text NOT NULL,
          target_type text NOT NULL,
          target_id text NOT NULL,
          evidence_redacted jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id)
        );
        CREATE TABLE events_outbox (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          aggregate_type text NOT NULL,
          aggregate_id uuid NOT NULL,
          event_type text NOT NULL,
          schema_version text NOT NULL,
          payload jsonb NOT NULL,
          published_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id)
        );
        CREATE INDEX outbox_unpublished_idx ON events_outbox(created_at) WHERE published_at IS NULL;
        """
    )

    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    cur_u = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    for t in TENANT_TABLES + ["tenants"]:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
    op.execute(f"CREATE POLICY tenant_isolation ON tenants USING (id = {cur_t}) WITH CHECK (id = {cur_t})")
    # A user may see their own memberships before a tenant is selected (needed to validate X-Tenant-Id).
    op.execute(
        f"CREATE POLICY tenant_isolation ON tenant_memberships "
        f"USING (tenant_id = {cur_t} OR user_id = {cur_u}) WITH CHECK (tenant_id = {cur_t})"
    )
    # Service account login binds app.user_id = client id so the row is visible pre-auth, still verified by hash.
    op.execute(
        f"CREATE POLICY tenant_isolation ON service_accounts "
        f"USING (tenant_id = {cur_t} OR id = {cur_u}) WITH CHECK (tenant_id = {cur_t})"
    )
    for t in ("audit_log", "events_outbox"):
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t})"
        )

    # Least privilege. audit_log is append-only for the runtime role (no UPDATE/DELETE).
    op.execute(
        """
        GRANT USAGE ON SCHEMA public TO fibercore_app;
        GRANT SELECT ON tenants, tenant_memberships, service_accounts, users_global TO fibercore_app;
        GRANT SELECT, INSERT ON audit_log TO fibercore_app;
        GRANT SELECT, INSERT, UPDATE ON events_outbox TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS events_outbox, audit_log, service_accounts, tenant_memberships, "
        "users_global, tenants CASCADE"
    )
    # Role is intentionally kept (may own grants in other DBs); drop manually if desired.
