-- REFERÊNCIA, NÃO MIGRAÇÃO PARA EXECUÇÃO DIRETA!
-- Integrar ao esquema/tipos de jobs/RLS do FiberCore 2.2 atual.
-- Se o sistema já tiver tabela de jobs, criar somente colunas ou tabela filha necessária.
CREATE TABLE IF NOT EXISTS fiber_speed_test_runs_reference (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    device_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    target TEXT NOT NULL CHECK (target IN ('CORE', 'INTERNET')),
    method TEXT NOT NULL DEFAULT 'TR143_HTTP',
    state TEXT NOT NULL,
    quality TEXT NULL CHECK (quality IN ('valid', 'partial', 'inconclusive')),
    wan_interface TEXT NULL,
    endpoint_name TEXT NULL,
    download_mbps NUMERIC(12,3) NULL,
    upload_mbps NUMERIC(12,3) NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    evidence_at TIMESTAMPTZ NULL,
    model TEXT NULL,
    firmware TEXT NULL,
    plan_snapshot JSONB NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_code TEXT NULL,
    safe_error TEXT NULL,
    task_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    adapter_version TEXT NULL
);
-- O projeto DEVE adaptar a política de isolamento RLS por tenant à convenção atual.
-- NÃO executar CREATE TABLE de referência como migração cega, nem usar sem RLS.
