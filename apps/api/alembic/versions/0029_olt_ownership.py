"""Ownership of an OLT by an Edge, with a generation (`owner_epoch`) and a two-phase transfer (ADR-0029 item 3).

* `owner_epoch` starts at 1 and goes up every time the owning Edge changes; a signed query repeats the epoch it was issued for, and the Edge refuses a lower
  one, so an envelope that outlived a transfer can never run on the old owner.
* `transfer_to` / `transfer_started_at`: phase 1 of a transfer. While set, the OLT gets no lease and no query is dispatched for it.
* `lease_until`: the last instant a lease was issued to the owner for (server clock). Phase 2 may only finish after it plus a clock margin (ADR-0029 item 3(b);
  the old Edge's explicit release (3(a)) is an optimisation not implemented: waiting out the lease is always safe).
Only the owner CLI (database owner) writes `owner_epoch`, `transfer_*` and the edge change: the application role loses the table-wide UPDATE/INSERT and keeps
exactly the columns the ingest and the lease issuer need.

Revision ID: 0029
Revises: 0028
"""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE olts
          ADD COLUMN owner_epoch integer NOT NULL DEFAULT 1 CHECK (owner_epoch >= 1),
          ADD COLUMN transfer_to uuid,
          ADD COLUMN transfer_started_at timestamptz,
          ADD COLUMN lease_until timestamptz,
          ADD CONSTRAINT olts_transfer_pair CHECK ((transfer_to IS NULL) = (transfer_started_at IS NULL)),
          ADD CONSTRAINT olts_transfer_edge FOREIGN KEY (tenant_id, transfer_to) REFERENCES edges(tenant_id, id);
        REVOKE UPDATE, INSERT ON olts FROM fibercore_app;
        GRANT INSERT (tenant_id, edge_id, name, vendor, model, firmware, support_level, observed_at) ON olts TO fibercore_app;
        GRANT UPDATE (vendor, model, firmware, support_level, observed_at, lease_until) ON olts TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        GRANT UPDATE, INSERT ON olts TO fibercore_app;
        ALTER TABLE olts DROP CONSTRAINT olts_transfer_edge, DROP CONSTRAINT olts_transfer_pair,
          DROP COLUMN lease_until, DROP COLUMN transfer_started_at, DROP COLUMN transfer_to, DROP COLUMN owner_epoch;
        """
    )
