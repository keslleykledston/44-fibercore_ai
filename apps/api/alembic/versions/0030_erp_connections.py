"""ERP Hub: conexões com o ERP do provedor (ADR-0033, HubSoft primeiro)

Uma linha por conexão (vários ERPs por provedor). A tabela NUNCA guarda segredo: `secret_ref` é só o nome do segredo no cofre/arquivo protegido do servidor.
A aplicação lê e cria; só atualiza as colunas de estado e o `enabled` (a identidade da conexão - provedor, URL, referência do segredo - não muda: uma conexão
nova é outra linha). Não há DELETE: desativar é `enabled = false`.

Revision ID: 0030
Revises: 0029
"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE erp_connections (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          provider text NOT NULL CHECK (provider IN ('hubsoft', 'ixc', 'sgp')),
          display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 120),
          auth_profile text NOT NULL CHECK (auth_profile IN ('hubsoft_oauth_credentials', 'ixc_user_api_token', 'sgp_legacy_token_app_body', 'sgp_v1_bearer_explicit')),
          transport_mode text NOT NULL DEFAULT 'cloud' CHECK (transport_mode IN ('cloud', 'edge')),
          sync_mode text NOT NULL DEFAULT 'lookup_only' CHECK (sync_mode IN ('lookup_only', 'incremental', 'snapshot')),
          base_url text NOT NULL CHECK (base_url ~ '^https://[a-z0-9.-]{{1,253}}$'),
          secret_ref text NOT NULL CHECK (secret_ref ~ '^[a-z0-9][a-z0-9._-]{{2,63}}$'),
          enabled boolean NOT NULL DEFAULT false,
          status text NOT NULL DEFAULT 'unconfigured' CHECK (status IN ('unconfigured', 'validating', 'healthy', 'degraded', 'unauthorized', 'rate_limited', 'offline', 'disabled')),
          last_tested_at timestamptz,
          last_success_at timestamptz,
          last_error_class text CHECK (last_error_class IS NULL OR last_error_class ~ '^[A-Z_]{{3,40}}$'),
          created_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, display_name)
        );
        ALTER TABLE erp_connections ENABLE ROW LEVEL SECURITY;
        ALTER TABLE erp_connections FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON erp_connections USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON erp_connections TO fibercore_app;
        GRANT UPDATE (enabled, status, last_tested_at, last_success_at, last_error_class, updated_at) ON erp_connections TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS erp_connections;")
