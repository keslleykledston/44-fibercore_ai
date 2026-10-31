"""ONT Configuration Manager, pré-visualização de mudanças (ADR-0036, FC24-03): pedidos de mudança de configuração por CPE

Uma linha por pré-visualização. Guarda só o necessário para auditar e para conferir a intenção: parâmetros TIPADOS e já validados (uma senha só aparece como o booleano "trocar": o valor dela não
tem coluna nem forma de entrar), o diff legível, a revisão da configuração em que o pedido se baseou e o hash da intenção. `status` só conhece `previewed` e `blocked`:
nesta entrega NADA executa em equipamento, então não existe estado de execução. A expiração é calculada por `expires_at`, não gravada.

Revision ID: 0033
Revises: 0032
"""
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE cpe_config_changes (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          cpe_id uuid NOT NULL,
          capability text NOT NULL CHECK (capability ~ '^[a-z][a-z0-9_]*(\\.[a-z0-9_]+){{1,3}}$'),
          instance_key text NOT NULL CHECK (instance_key ~ '^[a-z]{{3,10}}/[0-9]{{1,3}}$'),
          params jsonb NOT NULL,
          diff jsonb NOT NULL,
          base_revision text NOT NULL CHECK (base_revision ~ '^[0-9a-f]{{16}}$'),
          intent_hash text NOT NULL CHECK (intent_hash ~ '^[0-9a-f]{{64}}$'),
          risk text NOT NULL CHECK (risk IN ('R1', 'R2', 'R3')),
          approvals jsonb NOT NULL,
          status text NOT NULL DEFAULT 'previewed' CHECK (status IN ('previewed', 'blocked')),
          blockers jsonb NOT NULL DEFAULT '[]'::jsonb,
          warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
          requested_by uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          submitted_at timestamptz,
          PRIMARY KEY (tenant_id, id),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id) ON DELETE CASCADE,
          CHECK (expires_at > created_at)
        );
        CREATE INDEX cpe_config_changes_cpe ON cpe_config_changes (tenant_id, cpe_id, created_at DESC);
        ALTER TABLE cpe_config_changes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cpe_config_changes FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON cpe_config_changes USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON cpe_config_changes TO fibercore_app;
        GRANT UPDATE (status, blockers, submitted_at) ON cpe_config_changes TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cpe_config_changes;")
