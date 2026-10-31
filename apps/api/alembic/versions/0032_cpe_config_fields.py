"""ONT Configuration Manager, leitura (ADR-0034, FC24-01): campos de configuração observados por CPE

Uma linha por (CPE, campo canônico, instância): valor TIPADO de uma lista fechada (nenhum caminho TR-069/USP, nenhuma senha: só "senha definida" como booleano), com a hora do
dispositivo (`captured_at`) e a fonte (`edge` ou `mock`, esta marcada como sintética na API). A nuvem não escreve nada em equipamento por esta tabela.

Revision ID: 0032
Revises: 0031
"""
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE cpe_config_fields (
          tenant_id uuid NOT NULL,
          cpe_id uuid NOT NULL,
          name text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*){{1,3}}$'),
          instance_key text NOT NULL CHECK (instance_key ~ '^[a-z]{{3,10}}/[0-9]{{1,3}}$'),
          value jsonb NOT NULL,
          captured_at timestamptz NOT NULL,
          observed_at timestamptz NOT NULL,
          received_at timestamptz NOT NULL DEFAULT now(),
          data_model text NOT NULL CHECK (data_model IN ('tr098', 'tr181', 'usp')),
          protocol text NOT NULL CHECK (protocol IN ('tr069', 'tr369')),
          source text NOT NULL CHECK (source IN ('edge', 'mock')),
          PRIMARY KEY (tenant_id, cpe_id, name, instance_key),
          FOREIGN KEY (tenant_id, cpe_id) REFERENCES cpes(tenant_id, id) ON DELETE CASCADE,
          CHECK (name NOT LIKE '%password%' OR name LIKE '%.password.set')   -- um campo de senha só existe como "definida?" (booleano): o valor nunca tem onde morar
        );
        ALTER TABLE cpe_config_fields ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cpe_config_fields FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON cpe_config_fields USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON cpe_config_fields TO fibercore_app;
        GRANT UPDATE (value, captured_at, observed_at, received_at, data_model, protocol, source) ON cpe_config_fields TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cpe_config_fields;")
