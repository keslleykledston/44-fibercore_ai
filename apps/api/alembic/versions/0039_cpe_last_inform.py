"""CPE last Inform time as reported by the ACS (R-D004)

`cpes.observed_at` is when the Edge COLLECTED the snapshot, not when the CPE last contacted the ACS: a silent collector must never look like a silent
CPE. `last_inform_at` carries the ACS's own `_lastInform` and nothing else; it stays NULL until an Edge that sends it reports (an older Edge never does),
and a rule that needs it says "unknown" while it is NULL. It only moves forward.

Revision ID: 0039
Revises: 0038
"""
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cpes ADD COLUMN last_inform_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE cpes DROP COLUMN IF EXISTS last_inform_at")
