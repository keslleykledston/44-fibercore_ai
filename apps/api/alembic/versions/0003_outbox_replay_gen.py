"""outbox replay generation: lets replay bypass bus dedupe with a fresh Nats-Msg-Id

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE events_outbox ADD COLUMN replay_gen integer NOT NULL DEFAULT 0;
        GRANT SELECT (replay_gen) ON events_outbox TO fibercore_app;
        GRANT UPDATE (replay_gen) ON events_outbox TO fibercore_worker;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE events_outbox DROP COLUMN replay_gen")
