"""Speed Diagnostics (ADR-0038, amendment of 2026-10-31, option C): the owner's formal acceptance of the 3xx-redirect risk on the bench

The EG8145V5 was observed to FOLLOW a 3xx answer, so the gate stays at `redirect_unverified` unless the operator confirms an egress ACL or, by this amendment,
the responsible person accepts the residual risk for ONE vendor/model/firmware, for named LOGICAL test endpoints, for at most 90 days. The decision lives here,
in the database, written only by the owner CLI; the application role can only read it. The gate never reads a file: the repository document is the readable copy,
identified by `doc_sha256`, and a mismatch is an audit finding, not a security condition. Revoking sets `revoked_at` under the same exclusive lock the
registry promotion uses, so a revocation and the emission of an envelope cannot interleave.

Revision ID: 0036
Revises: 0035
"""
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE speed_risk_acceptances (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          vendor text NOT NULL CHECK (btrim(vendor) <> ''),
          model text NOT NULL CHECK (btrim(model) <> ''),
          firmware text NOT NULL CHECK (btrim(firmware) <> ''),
          endpoint_ids text[] NOT NULL CHECK (cardinality(endpoint_ids) BETWEEN 1 AND 8),
          approved_by text NOT NULL CHECK (btrim(approved_by) <> ''),
          accepted_on date NOT NULL,
          expires_on date NOT NULL,
          doc_ref text NOT NULL CHECK (doc_ref ~ '^docs/wiki/bench/ACEITE-risco-3xx-[a-z0-9-]+-[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}\\.md$'),
          doc_sha256 text NOT NULL CHECK (doc_sha256 ~ '^[0-9a-f]{{64}}$'),
          revoked_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          CHECK (expires_on > accepted_on AND expires_on <= accepted_on + 90)
        );
        CREATE INDEX speed_risk_acceptances_profile_idx ON speed_risk_acceptances (tenant_id, lower(vendor), lower(model), firmware);
        ALTER TABLE speed_risk_acceptances ENABLE ROW LEVEL SECURITY;
        ALTER TABLE speed_risk_acceptances FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON speed_risk_acceptances USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON speed_risk_acceptances TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS speed_risk_acceptances;")
