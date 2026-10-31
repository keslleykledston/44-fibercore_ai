"""Speed Diagnostics (ADR-0038): the Edge reports the health of its test nodes

The Edge probes each logical endpoint it knows (one small GET to a fixed /health path) and tells the Cloud only `ok` or `down` per id. Every endpoint is BOUND to
the one Edge that owns the node (`edge_id`, set by the owner CLI): a health report updates only the endpoints of the reporting Edge, and a test is only offered
for a bench CPE whose Edge owns the endpoint. An endpoint without an owning Edge is never ready. The application role may update exactly `health` and
`health_at`; it still cannot create, delete, rename or re-bind an endpoint (only the owner CLI does).

Revision ID: 0035
Revises: 0034
"""
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE speed_endpoints ADD COLUMN edge_id uuid;
        ALTER TABLE speed_endpoints ADD CONSTRAINT speed_endpoints_edge_fk FOREIGN KEY (tenant_id, edge_id) REFERENCES edges(tenant_id, id);
        GRANT UPDATE (health, health_at) ON speed_endpoints TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE UPDATE (health, health_at) ON speed_endpoints FROM fibercore_app;
        ALTER TABLE speed_endpoints DROP CONSTRAINT IF EXISTS speed_endpoints_edge_fk;
        ALTER TABLE speed_endpoints DROP COLUMN IF EXISTS edge_id;
        """
    )
