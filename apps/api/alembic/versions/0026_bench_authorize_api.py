"""Bench authorization through the API (ADR-0031 section 2(e), owner decision 2026-10-30): members from the operator role up may authorize ONE bench
maneuver, no longer only the owner at the host.

The authorization is the same record as before (`bench_authorizations`: bound to operation, bench target and parameters hash, single use, inside a
window) with its origin recorded: `authorized_via` = `owner_cli` (the owner at the host, unchanged) or `api` (an authenticated member, stored in
`authorized_by_user_id`). An API authorization is short (5..120 min), never `first_run` (that stays with the owner), and the job engine refuses to use it
for a job whose requester or approver is the person who authorized it.

Like the role change, the only writer is a SECURITY DEFINER function that only the dedicated `fibercore_rbac` connection may execute, so SQL reaching the
database through the application's normal role cannot arm a maneuver, not even by forging the session settings RLS reads.

Revision ID: 0026
Revises: 0025
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bench_authorizations
          ADD COLUMN authorized_via text NOT NULL DEFAULT 'owner_cli' CHECK (authorized_via IN ('owner_cli','api')),
          ADD COLUMN authorized_by_user_id uuid REFERENCES users_global(id),
          ADD CONSTRAINT bench_auth_origin CHECK ((authorized_via = 'api') = (authorized_by_user_id IS NOT NULL)),
          ADD CONSTRAINT bench_auth_api_not_first_run CHECK (authorized_via = 'owner_cli' OR NOT first_run),
          ADD CONSTRAINT bench_auth_api_short CHECK (authorized_via = 'owner_cli' OR window_end - window_start <= interval '2 hours');
        ALTER TABLE bench_authorizations DROP CONSTRAINT bench_authorizations_state_check;
        ALTER TABLE bench_authorizations ADD CONSTRAINT bench_authorizations_state_check CHECK (state IN ('open','consumed','revoked'));
        -- one live API authorization per target and operation: nobody stacks several to cover a series of maneuvers
        CREATE UNIQUE INDEX bench_authorizations_one_open_api ON bench_authorizations (tenant_id, cpe_id, operation)
          WHERE authorized_via = 'api' AND state = 'open';

        -- which role may authorize which bench operation (the maneuvers on the OLT side are for the engineering roles only)
        CREATE TABLE rbac_bench_authorizers (role text NOT NULL, operation text NOT NULL, PRIMARY KEY (role, operation));
        INSERT INTO rbac_bench_authorizers VALUES
          ('noc_n2','reboot_cpe'),('noc_n2','set_wifi_ssid'),
          ('engineer','reboot_cpe'),('engineer','set_wifi_ssid'),('engineer','onu_reset'),('engineer','onu_deactivate'),
          ('isp_admin','reboot_cpe'),('isp_admin','set_wifi_ssid'),('isp_admin','onu_reset'),('isp_admin','onu_deactivate');

        CREATE FUNCTION app_bench_authorize(p_actor uuid, p_tenant uuid, p_cpe uuid, p_operation text, p_params_hash text, p_minutes int) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE r text; locked boolean; aid uuid; wend timestamptz;
        BEGIN
          PERFORM set_config('app.tenant_id', p_tenant::text, true);
          PERFORM set_config('app.user_id', p_actor::text, true);
          SELECT m.role INTO r FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id
           WHERE m.tenant_id = p_tenant AND m.user_id = p_actor AND u.is_active;
          IF r IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_bench_authorizers WHERE role = r AND operation = p_operation) THEN RAISE EXCEPTION 'role_cannot_authorize'; END IF;
          IF p_minutes IS NULL OR p_minutes NOT BETWEEN 5 AND 120 THEN RAISE EXCEPTION 'window_invalid'; END IF;
          IF p_params_hash IS NULL OR p_params_hash !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'params_invalid'; END IF;
          IF NOT EXISTS (SELECT 1 FROM tenant_features WHERE tenant_id = p_tenant AND feature = 'bench_writes' AND enabled) THEN RAISE EXCEPTION 'bench_writes_disabled'; END IF;
          SELECT write_locked INTO locked FROM bench_targets WHERE tenant_id = p_tenant AND cpe_id = p_cpe;
          IF NOT FOUND THEN RAISE EXCEPTION 'target_not_bench'; END IF;
          IF locked THEN RAISE EXCEPTION 'target_write_locked'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended('bench-authorize|' || p_tenant::text || '|' || p_cpe::text || '|' || p_operation, 0));
          -- an API authorization that ran out unused no longer blocks a new one
          UPDATE bench_authorizations SET state = 'revoked'
           WHERE tenant_id = p_tenant AND cpe_id = p_cpe AND operation = p_operation AND authorized_via = 'api' AND state = 'open' AND window_end <= now();
          IF EXISTS (SELECT 1 FROM bench_authorizations WHERE tenant_id = p_tenant AND cpe_id = p_cpe AND operation = p_operation
                      AND authorized_via = 'api' AND state = 'open') THEN RAISE EXCEPTION 'authorization_already_open'; END IF;
          wend := now() + make_interval(mins => p_minutes);
          INSERT INTO bench_authorizations (tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by, authorized_via, authorized_by_user_id)
            VALUES (p_tenant, p_operation, p_cpe, p_params_hash, now(), wend, 'api:' || p_actor::text, 'api', p_actor) RETURNING id INTO aid;
          INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
            VALUES (p_tenant, p_actor, 'bench.authorize', 'cpe', p_cpe::text,
                    jsonb_build_object('authorization_id', aid, 'operation', p_operation, 'minutes', p_minutes, 'role', r));
          INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload)
            VALUES (p_tenant, 'bench_authorization', aid, 'bench.authorized', '1', jsonb_build_object('by', p_actor, 'operation', p_operation, 'cpe_id', p_cpe));
          RETURN jsonb_build_object('id', aid, 'window_end', wend);
        END $$;

        CREATE FUNCTION app_bench_revoke(p_actor uuid, p_tenant uuid, p_auth uuid) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE r text; a record;
        BEGIN
          PERFORM set_config('app.tenant_id', p_tenant::text, true);
          PERFORM set_config('app.user_id', p_actor::text, true);
          SELECT m.role INTO r FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id
           WHERE m.tenant_id = p_tenant AND m.user_id = p_actor AND u.is_active;
          SELECT id, operation, cpe_id, state, authorized_via INTO a FROM bench_authorizations WHERE tenant_id = p_tenant AND id = p_auth FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'authorization_not_found'; END IF;
          IF r IS NULL OR NOT EXISTS (SELECT 1 FROM rbac_bench_authorizers WHERE role = r AND operation = a.operation) THEN RAISE EXCEPTION 'role_cannot_authorize'; END IF;
          IF a.authorized_via <> 'api' THEN RAISE EXCEPTION 'owner_authorization'; END IF;   -- the owner's own records are the owner's to remove
          IF a.state <> 'open' THEN RAISE EXCEPTION 'authorization_not_open'; END IF;
          UPDATE bench_authorizations SET state = 'revoked' WHERE tenant_id = p_tenant AND id = p_auth;
          INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
            VALUES (p_tenant, p_actor, 'bench.authorize_revoke', 'cpe', a.cpe_id::text, jsonb_build_object('authorization_id', p_auth, 'operation', a.operation));
          RETURN jsonb_build_object('id', p_auth);
        END $$;
        REVOKE ALL ON FUNCTION app_bench_authorize(uuid, uuid, uuid, text, text, int) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app_bench_revoke(uuid, uuid, uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_bench_authorize(uuid, uuid, uuid, text, text, int) TO fibercore_rbac;
        GRANT EXECUTE ON FUNCTION app_bench_revoke(uuid, uuid, uuid) TO fibercore_rbac;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS app_bench_revoke(uuid, uuid, uuid);
        DROP FUNCTION IF EXISTS app_bench_authorize(uuid, uuid, uuid, text, text, int);
        DROP TABLE IF EXISTS rbac_bench_authorizers;
        DROP INDEX IF EXISTS bench_authorizations_one_open_api;
        DELETE FROM bench_authorizations WHERE authorized_via = 'api';
        ALTER TABLE bench_authorizations DROP CONSTRAINT bench_authorizations_state_check;
        DELETE FROM bench_authorizations WHERE state = 'revoked';
        ALTER TABLE bench_authorizations ADD CONSTRAINT bench_authorizations_state_check CHECK (state IN ('open','consumed'));
        ALTER TABLE bench_authorizations DROP CONSTRAINT bench_auth_api_short, DROP CONSTRAINT bench_auth_api_not_first_run, DROP CONSTRAINT bench_auth_origin,
          DROP COLUMN authorized_by_user_id, DROP COLUMN authorized_via;
        """
    )
