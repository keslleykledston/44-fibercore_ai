"""Profile Studio (v2.5, ADR-0040): immutable profile snapshots, mutable drafts, append-only dry runs

`olt_profile_snapshots` is what an OLT reported about ONE native profile, normalised to the typed model of `app.core.profile_studio`; it is evidence and is
IMMUTABLE (the application role can only SELECT and INSERT). Ids and names are LOCAL to the OLT. The fingerprint is computed by the API, never taken from the caller.

`profile_drafts` is the engineer's editable copy (clone-on-write: nothing here ever edits a profile on a device). It has a `row_version` for `If-Match`; the scope
(vendor, model, firmware, card, technology) and the source snapshot are fixed at creation, changing them is a new draft. There is no DELETE.

`profile_dry_runs` is append-only: the exact inputs, the per-OLT plans and their hashes, so a plan can be replayed and an approval can be bound to its hash.

Nothing in this migration writes to equipment or enables a write flag. The feature `profile_studio` is OFF by default (code catalog).

Revision ID: 0040
Revises: 0039
"""
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

STRATS = "('reuse_exact','adopt_reference','clone_new_revision','plan_migration')"


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE olt_profile_snapshots (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          olt_id uuid NOT NULL,
          native_type text NOT NULL CHECK (native_type ~ '^[a-z][a-z0-9_-]{{1,39}}$'),
          native_key text NOT NULL CHECK (native_key ~ '^[A-Za-z0-9._/:-]{{1,80}}$'),
          technology text NOT NULL CHECK (technology IN ('gpon', 'epon', 'xgspon')),
          vendor text NOT NULL CHECK (char_length(vendor) BETWEEN 1 AND 40),
          model text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 40),
          firmware text NOT NULL CHECK (char_length(firmware) BETWEEN 1 AND 60),
          pon_card text NOT NULL CHECK (char_length(pon_card) BETWEEN 1 AND 60),
          observed_at timestamptz NOT NULL,
          freshness text NOT NULL CHECK (freshness IN ('fresh', 'stale', 'unknown')),
          completeness text NOT NULL CHECK (completeness IN ('complete', 'partial', 'unknown')),
          reference_count integer CHECK (reference_count >= 0),
          fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{{64}}$'),
          settings jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object'),
          unknown_fields text[] NOT NULL DEFAULT '{{}}',
          evidence text CHECK (evidence IS NULL OR char_length(evidence) <= 40000),
          source text NOT NULL CHECK (source IN ('fixture', 'manual_import', 'edge_read')),
          created_by uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id)
        );
        CREATE INDEX olt_profile_snapshots_source ON olt_profile_snapshots (tenant_id, olt_id, native_key, observed_at DESC);
        ALTER TABLE olt_profile_snapshots ENABLE ROW LEVEL SECURITY;
        ALTER TABLE olt_profile_snapshots FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON olt_profile_snapshots USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON olt_profile_snapshots TO fibercore_app;

        CREATE TABLE profile_drafts (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
          owner_id uuid NOT NULL,
          source_snapshot_id uuid,
          technology text NOT NULL CHECK (technology IN ('gpon', 'epon', 'xgspon')),
          vendor text NOT NULL CHECK (char_length(vendor) BETWEEN 1 AND 40),
          model text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 40),
          firmware text NOT NULL CHECK (char_length(firmware) BETWEEN 1 AND 60),
          pon_card text NOT NULL CHECK (char_length(pon_card) BETWEEN 1 AND 60),
          profile_kind text NOT NULL CHECK (profile_kind IN ('dba', 'line', 'service', 'tcont', 'gem', 'onu_type', 'vlan', 'traffic', 'bundle')),
          target_olt_ids uuid[] NOT NULL DEFAULT '{{}}' CHECK (cardinality(target_olt_ids) <= 32),
          desired jsonb NOT NULL CHECK (jsonb_typeof(desired) = 'object'),
          vendor_extensions jsonb NOT NULL DEFAULT '{{}}' CHECK (jsonb_typeof(vendor_extensions) = 'object'),
          strategy text CHECK (strategy IS NULL OR strategy IN {STRATS}),
          reason text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 300),
          row_version bigint NOT NULL DEFAULT 1,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, source_snapshot_id) REFERENCES olt_profile_snapshots(tenant_id, id)
        );
        CREATE INDEX profile_drafts_owner ON profile_drafts (tenant_id, updated_at DESC);
        ALTER TABLE profile_drafts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE profile_drafts FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON profile_drafts USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON profile_drafts TO fibercore_app;
        GRANT UPDATE (name, target_olt_ids, desired, vendor_extensions, strategy, reason, row_version, updated_at) ON profile_drafts TO fibercore_app;

        CREATE TABLE profile_dry_runs (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          draft_id uuid NOT NULL,
          draft_row_version bigint NOT NULL,
          requested_by uuid NOT NULL,
          requested text CHECK (requested IS NULL OR requested IN {STRATS}),
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          inputs jsonb NOT NULL,
          plans jsonb NOT NULL,
          issues jsonb NOT NULL DEFAULT '[]',
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, draft_id) REFERENCES profile_drafts(tenant_id, id)
        );
        CREATE INDEX profile_dry_runs_draft ON profile_dry_runs (tenant_id, draft_id, created_at DESC);
        ALTER TABLE profile_dry_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE profile_dry_runs FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON profile_dry_runs USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON profile_dry_runs TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS profile_dry_runs; DROP TABLE IF EXISTS profile_drafts; DROP TABLE IF EXISTS olt_profile_snapshots;")
