"""login attempt ledger for lockout/throttling

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Global (pre-tenant) ledger: key is the lower-cased e-mail or the service-account id. No RLS: it holds no tenant data.
        CREATE TABLE login_attempts (
          id bigserial PRIMARY KEY,
          key text NOT NULL,
          success boolean NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX login_attempts_key_idx ON login_attempts(key, created_at DESC);
        GRANT SELECT, INSERT ON login_attempts TO fibercore_app;
        GRANT USAGE ON SEQUENCE login_attempts_id_seq TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS login_attempts")
