"""Bench operation `onu_reauthorize` (ADR-0030 H5): which roles may authorize it through the API

Only the engineering roles, like the other OLT-side maneuvers. Revision ID: 0044  Revises: 0043
"""
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("INSERT INTO rbac_bench_authorizers VALUES ('engineer','onu_reauthorize'),('isp_admin','onu_reauthorize') ON CONFLICT DO NOTHING;")


def downgrade() -> None:
    op.execute("DELETE FROM rbac_bench_authorizers WHERE operation = 'onu_reauthorize';")
