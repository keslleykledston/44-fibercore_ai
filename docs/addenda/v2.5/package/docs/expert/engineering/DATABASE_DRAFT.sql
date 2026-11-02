-- REFERÊNCIA CONCEITUAL: NÃO executar sem reconciliar com migrations existentes, tipos de IDs,
-- padrões de RLS e política de acesso/tenants do projeto real.
CREATE TABLE IF NOT EXISTS olt_profile_snapshots (
 tenant_id UUID NOT NULL, snapshot_id UUID NOT NULL, olt_id UUID NOT NULL,
 native_profile_type TEXT NOT NULL, native_profile_key TEXT NOT NULL,
 vendor TEXT NOT NULL, firmware TEXT NOT NULL, pon_card TEXT,
 observed_at TIMESTAMPTZ NOT NULL, freshness TEXT NOT NULL,
 reference_count INTEGER NULL CHECK(reference_count >= 0),
 fingerprint TEXT NOT NULL, normalized_json JSONB NOT NULL,
 immutable_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY (tenant_id, snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_olt_snapshots_source ON olt_profile_snapshots(tenant_id,olt_id,native_profile_key,observed_at DESC);
CREATE TABLE IF NOT EXISTS expert_profile_drafts (
 tenant_id UUID NOT NULL, draft_id UUID NOT NULL, source_snapshot_id UUID NULL,
 original_revision_id UUID NULL, owner_user_id UUID NOT NULL,
 desired_json JSONB NOT NULL, row_version BIGINT NOT NULL DEFAULT 1,
 reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY (tenant_id, draft_id),
 FOREIGN KEY(tenant_id,source_snapshot_id) REFERENCES olt_profile_snapshots(tenant_id,snapshot_id)
);
-- Rodar ALTER TABLE ... ENABLE ROW LEVEL SECURITY e políticas de isolamento do projeto
-- antes de uso real: NÃO fornecer política insegura nem depender apenas de session vars.
