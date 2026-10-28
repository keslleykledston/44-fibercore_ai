"""refresh tokens (rotating, reuse-detecting) and TOTP MFA

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Global (pre-tenant) like login_attempts: holds no tenant data. Only the SHA-256 of the opaque token is stored.
        CREATE TABLE refresh_tokens (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          family_id uuid NOT NULL,
          user_id uuid NOT NULL REFERENCES users_global(id) ON DELETE CASCADE,
          token_hash bytea NOT NULL UNIQUE,
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          family_expires_at timestamptz NOT NULL,
          used_at timestamptz,
          revoked_at timestamptz
        );
        CREATE INDEX refresh_tokens_family_idx ON refresh_tokens(family_id);
        CREATE INDEX refresh_tokens_user_idx ON refresh_tokens(user_id);
        GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_tokens TO fibercore_app;

        -- TOTP secret is stored encrypted (Fernet, key from MFA_ENCRYPTION_KEY); last_step blocks code replay.
        CREATE TABLE user_mfa (
          user_id uuid PRIMARY KEY REFERENCES users_global(id) ON DELETE CASCADE,
          secret_enc bytea NOT NULL,
          enabled boolean NOT NULL DEFAULT false,
          last_step bigint NOT NULL DEFAULT 0,
          created_at timestamptz NOT NULL DEFAULT now(),
          enabled_at timestamptz
        );
        GRANT SELECT, INSERT, UPDATE, DELETE ON user_mfa TO fibercore_app;

        CREATE TABLE mfa_recovery_codes (
          id bigserial PRIMARY KEY,
          user_id uuid NOT NULL REFERENCES users_global(id) ON DELETE CASCADE,
          code_hash bytea NOT NULL,
          used_at timestamptz
        );
        CREATE INDEX mfa_recovery_user_idx ON mfa_recovery_codes(user_id);
        GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_recovery_codes TO fibercore_app;
        GRANT USAGE ON SEQUENCE mfa_recovery_codes_id_seq TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mfa_recovery_codes; DROP TABLE IF EXISTS user_mfa; DROP TABLE IF EXISTS refresh_tokens;")
