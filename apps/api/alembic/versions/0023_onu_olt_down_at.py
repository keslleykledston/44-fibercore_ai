"""ONU: the OLT's own "last down time"

The OLT keeps, per ONU, when it last went down. The Edge reads it (SNMP, read-only) for ONUs that are offline and the cloud stores it in
its OWN column: `down_since` keeps meaning "a transition the Edge saw" (incident correlation reads it), while `olt_down_at` is only what the
OLT reports about itself (its clock may be a few minutes off) and is used by the offline report when no transition was observed.

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE onus ADD COLUMN olt_down_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE onus DROP COLUMN olt_down_at")
