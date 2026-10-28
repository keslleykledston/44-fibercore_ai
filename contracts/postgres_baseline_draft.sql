-- FiberCore AI baseline data model (DESIGN DRAFT, not a production-ready migration).
-- Implement as versioned Alembic migrations with application role restrictions.
-- RLS tenant context MUST be bound from validated auth membership in a transaction.
-- Use separate least-privilege non-owner DB runtime role with NO BYPASSRLS.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users_global (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  oidc_subject text UNIQUE NOT NULL,
  display_name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tenant_memberships (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  user_id uuid NOT NULL REFERENCES users_global(id),
  role text NOT NULL CHECK (role IN ('isp_admin','engineer','noc_n2','noc_n1','support','auditor','platform_support')),
  PRIMARY KEY (tenant_id, user_id)
);
CREATE TABLE IF NOT EXISTS edges (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL,
  site_name text,
  certificate_serial text,
  version text,
  last_heartbeat_at timestamptz,
  status text NOT NULL DEFAULT 'unknown',
  PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS olts (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  edge_id uuid,
  name text NOT NULL,
  vendor text NOT NULL,
  model text,
  firmware text,
  credential_secret_ref text, -- reference, NEVER secret itself
  data_quality text NOT NULL DEFAULT 'unknown',
  observed_at timestamptz,
  PRIMARY KEY(tenant_id,id),
  FOREIGN KEY(tenant_id,edge_id) REFERENCES edges(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS pon_ports (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  olt_id uuid NOT NULL,
  pon_path text NOT NULL,
  status text NOT NULL DEFAULT 'unknown',
  PRIMARY KEY(tenant_id,id),
  UNIQUE (tenant_id,olt_id,pon_path),
  FOREIGN KEY (tenant_id,olt_id) REFERENCES olts(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS onus (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  olt_id uuid NOT NULL,
  pon_id uuid,
  serial text NOT NULL,
  status text NOT NULL DEFAULT 'unknown',
  rx_dbm numeric(7,2),
  observed_at timestamptz,
  data_quality text NOT NULL DEFAULT 'unknown',
  PRIMARY KEY(tenant_id,id),
  FOREIGN KEY (tenant_id,olt_id) REFERENCES olts(tenant_id,id),
  FOREIGN KEY (tenant_id,pon_id) REFERENCES pon_ports(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS onus_tenant_serial_idx ON onus(tenant_id,serial);
CREATE TABLE IF NOT EXISTS cpes (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  canonical_serial text,
  vendor text,
  model text,
  firmware text,
  PRIMARY KEY(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS cpe_protocol_bindings (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  cpe_id uuid NOT NULL,
  protocol text NOT NULL CHECK (protocol IN ('tr069','tr369')),
  external_id text NOT NULL,
  connector_id text NOT NULL,
  observed_at timestamptz,
  PRIMARY KEY (tenant_id,id),
  UNIQUE (tenant_id,connector_id,protocol,external_id),
  FOREIGN KEY(tenant_id,cpe_id) REFERENCES cpes(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS customers (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  erp_source text,
  erp_customer_id text,
  display_name text,
  contract_status text,
  financial_status text,
  PRIMARY KEY(tenant_id,id),
  UNIQUE(tenant_id,erp_source,erp_customer_id)
);
CREATE TABLE IF NOT EXISTS associations (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  onu_id uuid NOT NULL,
  cpe_id uuid,
  customer_id uuid NOT NULL,
  score numeric(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'suggested',
  reviewed_by uuid,
  PRIMARY KEY(tenant_id,id),
  FOREIGN KEY(tenant_id,onu_id) REFERENCES onus(tenant_id,id),
  FOREIGN KEY(tenant_id,cpe_id) REFERENCES cpes(tenant_id,id),
  FOREIGN KEY(tenant_id,customer_id) REFERENCES customers(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS jobs (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  target_type text NOT NULL,
  target_id uuid NOT NULL,
  operation text NOT NULL,
  intent_hash char(64) NOT NULL,
  idempotency_key text NOT NULL,
  risk text NOT NULL CHECK (risk IN ('R0','R1','R2','R3')),
  status text NOT NULL DEFAULT 'draft',
  approval_id uuid,
  external_task_id text,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id),
  UNIQUE(tenant_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS events_outbox (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  event_type text NOT NULL,
  schema_version text NOT NULL,
  payload jsonb NOT NULL,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx ON events_outbox(created_at) WHERE published_at IS NULL;
CREATE TABLE IF NOT EXISTS audit_log (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  actor_id uuid,
  action text NOT NULL,
  target_type text NOT NULL,
  target_id text NOT NULL,
  evidence_redacted jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,id)
);

-- RLS baseline: auth membership validation in app is additional and mandatory.
DO $$
DECLARE tablename text;
BEGIN
  FOREACH tablename IN ARRAY ARRAY['tenants','tenant_memberships','edges','olts','pon_ports','onus','cpes','cpe_protocol_bindings','customers','associations','jobs','events_outbox','audit_log'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tablename);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tablename);
    IF tablename = 'tenants' THEN
      EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) WITH CHECK (id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)', tablename);
    ELSE
      EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)', tablename);
    END IF;
  END LOOP;
END $$;
-- users_global only accessible through dedicated auth service role with row-scoped SELECT API.
-- Service role grants, policy update idempotence, migrations and credentials are not defined here.
-- Implement INSERT/UPDATE append-only protections for audit_log separately with least privilege.
