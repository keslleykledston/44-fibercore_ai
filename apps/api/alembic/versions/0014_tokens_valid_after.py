"""users_global.tokens_valid_after: verifiable revocation of already-issued access tokens

An administrator MFA reset (and any future "sign this person out everywhere") must end sessions NOW, not when the 15-minute access token
expires. Every access token carries its issue time (iat); the authenticator rejects a user token issued before this instant.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users_global ADD COLUMN tokens_valid_after timestamptz;
        GRANT UPDATE (tokens_valid_after) ON users_global TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("REVOKE UPDATE (tokens_valid_after) ON users_global FROM fibercore_app; ALTER TABLE users_global DROP COLUMN tokens_valid_after;")
