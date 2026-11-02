"""olt_query_latest.source may be 'mock' (DEMO tenant only, written by the owner CLI `olt-board-mock`)

The screens label a 'mock' value as a demonstration; the CLI refuses any tenant that is not the demonstration tenant and never overwrites an inventory read from the equipment. Revision ID: 0043  Revises: 0042
"""
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE olt_query_latest DROP CONSTRAINT olt_query_latest_source_check; "
               "ALTER TABLE olt_query_latest ADD CONSTRAINT olt_query_latest_source_check CHECK (source IN ('job', 'routine', 'mock'));")


def downgrade() -> None:
    op.execute("DELETE FROM olt_query_latest WHERE source = 'mock'; ALTER TABLE olt_query_latest DROP CONSTRAINT olt_query_latest_source_check; "
               "ALTER TABLE olt_query_latest ADD CONSTRAINT olt_query_latest_source_check CHECK (source IN ('job', 'routine'));")
