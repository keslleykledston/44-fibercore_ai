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
    # Identity data is never merged automatically: two CPEs that only differ by case/spaces, or one CPE with several external ids for the
    # same (connector, protocol), may be different physical devices, and picking a survivor would silently re-point a management binding.
    # So the migration REFUSES to run over such data and says exactly what to fix (counts only; no identifiers in the message).
    # Block concurrent WRITES (reads continue) for the whole diagnosis + rewrite, so no collision can appear between the check and the UPDATE.
    op.execute("LOCK TABLE cpes, cpe_protocol_bindings IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        DECLARE serial_collisions int; binding_collisions int;
        BEGIN
          SELECT count(*) INTO serial_collisions FROM (
            SELECT 1 FROM cpes GROUP BY tenant_id, upper(btrim(canonical_serial)) HAVING count(*) > 1) x;
          SELECT count(*) INTO binding_collisions FROM (
            SELECT 1 FROM cpe_protocol_bindings GROUP BY tenant_id, cpe_id, connector_id, protocol HAVING count(*) > 1) y;
          IF serial_collisions > 0 OR binding_collisions > 0 THEN
            RAISE EXCEPTION '0013 refused: % CPE serial group(s) differ only by case/spaces and % CPE(s) have several external ids for the same connector+protocol. Reconcile them by hand (decide which device is real), then re-run.',
              serial_collisions, binding_collisions;
          END IF;
        END $$;
        """
    )
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
