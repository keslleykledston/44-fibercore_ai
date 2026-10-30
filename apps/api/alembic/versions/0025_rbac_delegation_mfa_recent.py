"""RBAC delivery 5 (ADR-0031): platform delegation with a deadline, and the recency of the second factor.

* `membership_delegations`: the ONLY way a platform operator reaches a workspace. The principal resolver asks for an unrevoked, unexpired row on EVERY
  request. `platform_support` can no longer be a plain membership role: legacy rows are removed here (audited) and the role CHECK refuses new ones.
* `users_global.is_platform_operator`: only accounts the platform itself marked (CLI, host access) can be delegated to, so a workspace administrator
  cannot hand workspace access to an arbitrary account, nor probe which e-mail addresses exist.
* `refresh_tokens.mfa_at`: when the session family last proved a second factor (login with MFA, or a step-up); a refresh carries it, never renews it.
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

NEW = "('isp_admin','access_manager','engineer','noc_n2','noc_n1','support','auditor')"
PREV = "('isp_admin','access_manager','engineer','noc_n2','noc_n1','support','auditor','platform_support')"


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    cur_u = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    op.execute(
        f"""
        ALTER TABLE refresh_tokens ADD COLUMN mfa_at timestamptz;
        ALTER TABLE users_global ADD COLUMN is_platform_operator boolean NOT NULL DEFAULT false;

        -- legacy platform_support memberships had no deadline and no reason: they end now and only come back as a delegation
        INSERT INTO audit_log (tenant_id, actor_id, action, target_type, target_id, evidence_redacted)
          SELECT tenant_id, NULL, 'member.platform_support_invalidated', 'user', user_id::text,
                 jsonb_build_object('reason', 'migration 0025: platform access is only by delegation')
            FROM tenant_memberships WHERE role = 'platform_support';
        UPDATE users_global SET tokens_valid_after = clock_timestamp()
         WHERE id IN (SELECT user_id FROM tenant_memberships WHERE role = 'platform_support');
        DELETE FROM tenant_memberships WHERE role = 'platform_support';
        ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
        ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check CHECK (role IN {NEW});

        CREATE TABLE membership_delegations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          user_id uuid NOT NULL REFERENCES users_global(id),
          granted_by uuid NOT NULL REFERENCES users_global(id),
          reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 10 AND 300),
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          revoked_at timestamptz,
          revoked_by uuid REFERENCES users_global(id),
          CONSTRAINT delegation_max_8h CHECK (expires_at > created_at AND expires_at <= created_at + interval '8 hours'),
          CONSTRAINT delegation_not_self CHECK (user_id <> granted_by),
          CONSTRAINT delegation_revoke_pair CHECK ((revoked_at IS NULL) = (revoked_by IS NULL))
        );
        CREATE INDEX membership_delegations_user_idx ON membership_delegations (user_id, expires_at);
        CREATE INDEX membership_delegations_tenant_idx ON membership_delegations (tenant_id, created_at DESC);
        ALTER TABLE membership_delegations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE membership_delegations FORCE ROW LEVEL SECURITY;
        -- the delegate reads its own rows before choosing a workspace (like tenant_memberships); only the workspace itself writes them
        CREATE POLICY tenant_isolation ON membership_delegations
          USING (tenant_id = {cur_t} OR user_id = {cur_u}) WITH CHECK (tenant_id = {cur_t});
        -- the delegate may read (only) the workspace it is delegated to, exactly like a member reads its own
        DROP POLICY tenant_read ON tenants;
        CREATE POLICY tenant_read ON tenants FOR SELECT
          USING (id = {cur_t} OR id IN (SELECT tenant_id FROM tenant_memberships WHERE user_id = {cur_u})
                 OR id IN (SELECT tenant_id FROM membership_delegations WHERE user_id = {cur_u} AND revoked_at IS NULL AND clock_timestamp() < expires_at));
        GRANT SELECT, INSERT ON membership_delegations TO fibercore_app;
        GRANT UPDATE (revoked_at, revoked_by) ON membership_delegations TO fibercore_app;

        -- a delegation is a record: only its revocation can change, and only once
        CREATE FUNCTION membership_delegations_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'delegation already revoked' USING ERRCODE = 'check_violation'; END IF;
          IF NEW.id <> OLD.id OR NEW.tenant_id <> OLD.tenant_id OR NEW.user_id <> OLD.user_id OR NEW.granted_by <> OLD.granted_by
             OR NEW.reason <> OLD.reason OR NEW.created_at <> OLD.created_at OR NEW.expires_at <> OLD.expires_at THEN
            RAISE EXCEPTION 'a delegation can only be revoked' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER membership_delegations_immutable BEFORE UPDATE ON membership_delegations
          FOR EACH ROW EXECUTE FUNCTION membership_delegations_immutable();
        """
    )


def downgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    cur_u = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    op.execute(
        f"""
        DROP POLICY tenant_read ON tenants;
        CREATE POLICY tenant_read ON tenants FOR SELECT
          USING (id = {cur_t} OR id IN (SELECT tenant_id FROM tenant_memberships WHERE user_id = {cur_u}));
        DROP TABLE IF EXISTS membership_delegations;
        DROP FUNCTION IF EXISTS membership_delegations_immutable();
        ALTER TABLE tenant_memberships DROP CONSTRAINT tenant_memberships_role_check;
        ALTER TABLE tenant_memberships ADD CONSTRAINT tenant_memberships_role_check CHECK (role IN {PREV});
        ALTER TABLE users_global DROP COLUMN IF EXISTS is_platform_operator;
        ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS mfa_at;
        """
    )
