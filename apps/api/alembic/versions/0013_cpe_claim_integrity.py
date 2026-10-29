"""CPE identity is a CLAIM made by the device: canonical serial form + one external id per (cpe, connector, protocol)

A CWMP-reachable device chooses its own serial. The Cloud therefore (a) stores serials in ONE canonical form (trimmed, upper case:
the ERP matches on upper(canonical_serial), so 'abc' and 'ABC' must not be two CPEs) and (b) lets a CPE carry at most ONE external id
per (connector, protocol), so a second device claiming the same serial cannot attach itself to an existing CPE. Ingestion already
ignores such claims; these constraints are the persistent guarantee under concurrency.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE cpes SET canonical_serial = upper(btrim(canonical_serial)) WHERE canonical_serial <> upper(btrim(canonical_serial));
        ALTER TABLE cpes ADD CONSTRAINT cpes_canonical_serial_form CHECK (canonical_serial <> '' AND canonical_serial = upper(btrim(canonical_serial)));
        CREATE UNIQUE INDEX cpe_bindings_one_external_id_per_key ON cpe_protocol_bindings (tenant_id, cpe_id, connector_id, protocol);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX cpe_bindings_one_external_id_per_key;
        ALTER TABLE cpes DROP CONSTRAINT cpes_canonical_serial_form;
        """
    )
