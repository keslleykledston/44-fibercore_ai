"""CPE last Inform time as reported by the ACS (R-D004)

`cpes.observed_at` is when the Edge COLLECTED the snapshot, not when the CPE last contacted the ACS: a silent collector must never look like a silent
CPE. `last_inform_at` carries the ACS's own `_lastInform` and nothing else; it stays NULL until an Edge that sends it reports (an older Edge never does),
and a rule that needs it says "unknown" while it is NULL. It only moves forward.
`last_inform_observed_at` is when the Edge last REPORTED a `last_inform_at` (the collection time of the snapshot that carried it). A snapshot that omits the field
never renews it, so an old Inform kept from an earlier snapshot cannot borrow the freshness of a newer snapshot that said nothing about it.

Revision ID: 0039
Revises: 0038
"""
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cpes ADD COLUMN last_inform_at timestamptz, ADD COLUMN last_inform_observed_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE cpes DROP COLUMN IF EXISTS last_inform_at, DROP COLUMN IF EXISTS last_inform_observed_at")
