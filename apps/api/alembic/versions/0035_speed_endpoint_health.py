"""Speed Diagnostics (ADR-0038): the Edge reports the health of its test nodes

The Edge probes each logical endpoint it knows (one small GET to a fixed /health path) and tells the Cloud only `ok` or `down` per id. The application role may
therefore update exactly these two columns of `speed_endpoints`; it still cannot create, delete or rename an endpoint (only the owner CLI does).

Revision ID: 0035
Revises: 0034
"""
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT UPDATE (health, health_at) ON speed_endpoints TO fibercore_app;")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (health, health_at) ON speed_endpoints FROM fibercore_app;")
