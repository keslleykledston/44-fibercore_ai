"""Immutable profile revisions (v2.5, FC251-08): a reviewed draft becomes a numbered, frozen revision with a changelog

`profile_revisions` keeps what was PUBLISHED: a copy of the draft's typed settings at one `row_version`, the content hash, the changelog and who prepared and who approved it
(maker-checker: the approver is NOT among the people who ever created or edited the draft). The application role can only SELECT and INSERT (no UPDATE, no DELETE): a revision is
never edited, a change is a new draft and a new revision. Publishing sends NOTHING to any OLT. `profile_drafts.editor_ids` records everyone who ever saved the draft (an edit, even a no-op one, adds the editor), so the checker rule cannot be
bypassed by a harmless-looking save. Revision ID: 0042  Revises: 0041
"""
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        ALTER TABLE profile_drafts ADD COLUMN editor_ids uuid[] NOT NULL DEFAULT '{{}}';
        UPDATE profile_drafts SET editor_ids = ARRAY[owner_id];
        GRANT UPDATE (editor_ids) ON profile_drafts TO fibercore_app;

        CREATE TABLE profile_revisions (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          draft_id uuid NOT NULL,
          draft_row_version bigint NOT NULL,
          name_key text NOT NULL CHECK (char_length(name_key) BETWEEN 1 AND 80),
          revision_no integer NOT NULL CHECK (revision_no >= 1),
          name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
          profile_kind text NOT NULL,
          technology text NOT NULL,
          vendor text NOT NULL,
          model text NOT NULL,
          firmware text NOT NULL,
          pon_card text NOT NULL,
          desired jsonb NOT NULL CHECK (jsonb_typeof(desired) = 'object'),
          content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{{64}}$'),
          changelog text NOT NULL CHECK (char_length(changelog) BETWEEN 3 AND 2000),
          prepared_by uuid NOT NULL,
          approved_by uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, draft_id) REFERENCES profile_drafts(tenant_id, id),
          CHECK (prepared_by <> approved_by),
          UNIQUE (tenant_id, draft_id, draft_row_version),
          UNIQUE (tenant_id, name_key, revision_no)
        );
        CREATE INDEX profile_revisions_recent ON profile_revisions (tenant_id, created_at DESC);
        ALTER TABLE profile_revisions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE profile_revisions FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON profile_revisions USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON profile_revisions TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS profile_revisions; ALTER TABLE profile_drafts DROP COLUMN IF EXISTS editor_ids;")
