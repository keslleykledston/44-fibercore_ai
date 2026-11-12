"""OLT credentials typed on the screen, sealed in the browser for the Edge (ADR-0045): `olt_secret_deliveries`, the Edge's seal key on `edges`, the blob reader and the retention function

What the database holds is only CIPHERTEXT (an AES-GCM blob under a key only the Edge's private key can derive); never the plain text. On top of that, defence in depth so the blob is not even readable by accident:

* the application role has NO SELECT on the `sealed` column (a column-level grant list that leaves it out): `SELECT *`, `RETURNING sealed` or a stray join from a user route fail with "permission denied". A derived
  `has_blob` column answers "is there still a blob?". The one reader is the SECURITY DEFINER function `app_secret_delivery_blob(id, lease_token)`, which returns the blob only for the DISPATCHED delivery of the session
  tenant whose CURRENT lease token the caller presents (the token is minted in the same transaction by `GET /v1/edge/secret-deliveries/next`).
* a terminal delivery (APPLIED, FAILED, EXPIRED, CANCELLED) can never hold a blob: a trigger nulls it and a CHECK refuses it; once NULL a blob cannot be put back; a terminal status cannot move.
* at most ONE delivery in flight per Edge, enforced by a partial unique index (the API serialises on a per-Edge advisory lock first; the index is the net underneath).
* the retention function `app_sweep_secret_deliveries()` (SECURITY DEFINER, EXECUTE only for `fibercore_worker`, like 0047) expires and scrubs blobs in EVERY tenant, so a blob never outlives `expires_at` (<= 1 h)
  because nobody polled. The worker role gets no grant on the table, only that entry point.

Reversible. Revision ID: 0050  Revises: 0049
"""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

APP_SELECT_COLS = ("tenant_id, id, edge_id, olt_id, olt_name, kind, key_id, expires_at, has_blob, status, lease_token, lease_until, attempts, code, created_by, created_at, updated_at, finished_at")
APP_UPDATE_COLS = "status, lease_token, lease_until, attempts, code, updated_at, finished_at, sealed"
EDGE_COLS = "seal_public_key, seal_key_id, seal_key_state, seal_key_reported_at, seal_key_confirmed_by, seal_key_confirmed_at"


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        -- the Edge's public seal key (not a secret) and whether a person confirmed its fingerprint
        ALTER TABLE edges
          ADD COLUMN seal_public_key text,
          ADD COLUMN seal_key_id text,
          ADD COLUMN seal_key_state text,
          ADD COLUMN seal_key_reported_at timestamptz,
          ADD COLUMN seal_key_confirmed_by uuid,
          ADD COLUMN seal_key_confirmed_at timestamptz,
          ADD CONSTRAINT edges_seal_key_state_values CHECK (seal_key_state IS NULL OR seal_key_state IN ('pending', 'confirmed')),
          ADD CONSTRAINT edges_seal_key_together CHECK ((seal_public_key IS NULL) = (seal_key_id IS NULL) AND (seal_key_id IS NULL) = (seal_key_state IS NULL)),
          ADD CONSTRAINT edges_seal_key_confirmed CHECK (seal_key_state IS DISTINCT FROM 'confirmed' OR (seal_key_confirmed_by IS NOT NULL AND seal_key_confirmed_at IS NOT NULL));
        GRANT UPDATE ({EDGE_COLS}) ON edges TO fibercore_app;

        CREATE TABLE olt_secret_deliveries (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL,                       -- the delivery_id chosen by the browser (it is part of the AAD); unique per tenant
          edge_id uuid NOT NULL,
          olt_id uuid NOT NULL,
          olt_name text NOT NULL,                 -- the OLT name at the time (part of the AAD the Edge checks)
          kind text NOT NULL CHECK (kind IN ('ssh_login', 'snmp_community')),
          key_id text NOT NULL CHECK (key_id ~ '^[0-9a-f]{{16}}$'),
          expires_at timestamptz NOT NULL,
          sealed bytea,                           -- CIPHERTEXT only; NULL as soon as the delivery is terminal or expired
          has_blob boolean GENERATED ALWAYS AS (sealed IS NOT NULL) STORED,
          status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DISPATCHED', 'APPLIED', 'FAILED', 'EXPIRED', 'CANCELLED')),
          lease_token uuid,
          lease_until timestamptz,
          attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
          code text,
          created_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          finished_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, edge_id) REFERENCES edges(tenant_id, id),
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id) ON DELETE CASCADE,
          CHECK (sealed IS NULL OR (status IN ('PENDING', 'DISPATCHED') AND octet_length(sealed) BETWEEN 95 AND 2048)),
          CHECK (status <> 'DISPATCHED' OR (lease_token IS NOT NULL AND lease_until IS NOT NULL))
        );
        -- ONE delivery in flight per Edge, decided by the database
        CREATE UNIQUE INDEX olt_secret_deliveries_one_in_flight ON olt_secret_deliveries (tenant_id, edge_id) WHERE status = 'DISPATCHED';
        CREATE INDEX olt_secret_deliveries_queue ON olt_secret_deliveries (tenant_id, edge_id, created_at) WHERE status IN ('PENDING', 'DISPATCHED');
        CREATE INDEX olt_secret_deliveries_olt ON olt_secret_deliveries (tenant_id, olt_id, created_at DESC);
        CREATE INDEX olt_secret_deliveries_blob_expiry ON olt_secret_deliveries (expires_at) WHERE sealed IS NOT NULL;

        CREATE FUNCTION olt_secret_deliveries_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF OLD.status IN ('APPLIED', 'FAILED', 'EXPIRED', 'CANCELLED') AND NEW.status <> OLD.status THEN
              RAISE EXCEPTION 'olt_secret_deliveries: a terminal delivery cannot change state';
            END IF;
            IF OLD.sealed IS NULL AND NEW.sealed IS NOT NULL THEN
              RAISE EXCEPTION 'olt_secret_deliveries: a scrubbed blob cannot be put back';
            END IF;
            IF NEW.sealed IS NOT NULL AND NEW.sealed IS DISTINCT FROM OLD.sealed THEN
              RAISE EXCEPTION 'olt_secret_deliveries: the blob can only be erased, never replaced';
            END IF;
          END IF;
          IF NEW.status NOT IN ('PENDING', 'DISPATCHED') THEN
            NEW.sealed := NULL;               -- a terminal delivery never keeps a blob, whatever the caller forgot
            IF NEW.finished_at IS NULL THEN NEW.finished_at := now(); END IF;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER olt_secret_deliveries_guard BEFORE INSERT OR UPDATE ON olt_secret_deliveries
          FOR EACH ROW EXECUTE FUNCTION olt_secret_deliveries_guard();

        ALTER TABLE olt_secret_deliveries ENABLE ROW LEVEL SECURITY;
        ALTER TABLE olt_secret_deliveries FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON olt_secret_deliveries USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        -- the application role: no DELETE, and no SELECT on `sealed` (the blob is read only through app_secret_delivery_blob)
        GRANT SELECT ({APP_SELECT_COLS}) ON olt_secret_deliveries TO fibercore_app;
        GRANT INSERT (tenant_id, id, edge_id, olt_id, olt_name, kind, key_id, expires_at, sealed, created_by) ON olt_secret_deliveries TO fibercore_app;
        GRANT UPDATE ({APP_UPDATE_COLS}) ON olt_secret_deliveries TO fibercore_app;

        -- the ONLY way to read a blob: the DISPATCHED delivery of the session tenant, with the lease token the caller was just handed
        CREATE FUNCTION app_secret_delivery_blob(p_id uuid, p_lease uuid) RETURNS bytea
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT sealed FROM olt_secret_deliveries
           WHERE tenant_id = {cur_t} AND id = p_id AND lease_token = p_lease AND status = 'DISPATCHED' AND lease_until > now() AND expires_at > now()
        $$;
        REVOKE ALL ON FUNCTION app_secret_delivery_blob(uuid, uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_secret_delivery_blob(uuid, uuid) TO fibercore_app;

        -- retention, every tenant, on a clock (called by the job-sweeper worker): an overdue PENDING/DISPATCHED delivery becomes EXPIRED and loses its blob; any blob left on a terminal row is erased
        DO $$ BEGIN
          EXECUTE format($p$CREATE POLICY retention_scan ON olt_secret_deliveries FOR SELECT TO %I USING (sealed IS NOT NULL OR status IN ('PENDING','DISPATCHED'))$p$, current_user);
        END $$;
        CREATE FUNCTION app_sweep_secret_deliveries() RETURNS TABLE (expired integer, scrubbed integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE t uuid; a integer; b integer;
        BEGIN
          expired := 0; scrubbed := 0;
          FOR t IN SELECT DISTINCT tenant_id FROM olt_secret_deliveries WHERE sealed IS NOT NULL OR status IN ('PENDING', 'DISPATCHED') LOOP
            PERFORM set_config('app.tenant_id', t::text, true);
            WITH s AS (UPDATE olt_secret_deliveries SET status = 'EXPIRED', sealed = NULL, updated_at = now()
                        WHERE status IN ('PENDING', 'DISPATCHED') AND expires_at <= now() RETURNING 1)
            SELECT count(*) INTO a FROM s;
            WITH s AS (UPDATE olt_secret_deliveries SET sealed = NULL, updated_at = now()
                        WHERE sealed IS NOT NULL AND status NOT IN ('PENDING', 'DISPATCHED') RETURNING 1)
            SELECT count(*) INTO b FROM s;
            expired := expired + a; scrubbed := scrubbed + b;
          END LOOP;
          PERFORM set_config('app.tenant_id', '', true);
          RETURN NEXT;
        END $$;
        REVOKE ALL ON FUNCTION app_sweep_secret_deliveries() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_sweep_secret_deliveries() TO fibercore_worker;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP FUNCTION IF EXISTS app_sweep_secret_deliveries();
        DROP FUNCTION IF EXISTS app_secret_delivery_blob(uuid, uuid);
        DROP TABLE IF EXISTS olt_secret_deliveries;
        DROP FUNCTION IF EXISTS olt_secret_deliveries_guard();
        REVOKE UPDATE ({EDGE_COLS}) ON edges FROM fibercore_app;
        ALTER TABLE edges DROP CONSTRAINT IF EXISTS edges_seal_key_confirmed, DROP CONSTRAINT IF EXISTS edges_seal_key_together, DROP CONSTRAINT IF EXISTS edges_seal_key_state_values,
          DROP COLUMN IF EXISTS seal_key_confirmed_at, DROP COLUMN IF EXISTS seal_key_confirmed_by, DROP COLUMN IF EXISTS seal_key_reported_at,
          DROP COLUMN IF EXISTS seal_key_state, DROP COLUMN IF EXISTS seal_key_id, DROP COLUMN IF EXISTS seal_public_key;
        """
    )
