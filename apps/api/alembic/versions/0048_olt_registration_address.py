"""Fleet Manager: management address and SNMP version of a registered OLT (ADR-0041 amendment to D3)

The registration gains `mgmt_address` (the OLT's management IP, informational: the Edge keeps using the address of its own configuration) and `snmp_version`. The address is NOT a
secret, but it is write-only for readers: the API only ever returns a masked form. Credentials (login, password, SNMP community) are still NOT stored here (they stay in the Edge's
local store; D3 unchanged for them). Revision ID: 0048  Revises: 0047
"""
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE olts
          ADD COLUMN mgmt_address inet,
          ADD COLUMN snmp_version text,
          ADD CONSTRAINT olts_snmp_version_values CHECK (snmp_version IS NULL OR snmp_version IN ('v2c', 'v3')),
          ADD CONSTRAINT olts_mgmt_address_host CHECK (mgmt_address IS NULL OR masklen(mgmt_address) = CASE family(mgmt_address) WHEN 4 THEN 32 ELSE 128 END);
        GRANT INSERT (mgmt_address, snmp_version) ON olts TO fibercore_app;
        GRANT UPDATE (mgmt_address, snmp_version) ON olts TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE INSERT (mgmt_address, snmp_version) ON olts FROM fibercore_app;
        REVOKE UPDATE (mgmt_address, snmp_version) ON olts FROM fibercore_app;
        ALTER TABLE olts DROP CONSTRAINT IF EXISTS olts_mgmt_address_host, DROP CONSTRAINT IF EXISTS olts_snmp_version_values,
          DROP COLUMN IF EXISTS snmp_version, DROP COLUMN IF EXISTS mgmt_address;
        """
    )
