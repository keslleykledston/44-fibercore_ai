"""Cache primeiro das consultas à OLT (ADR-0032 item 4): último valor por consulta e série de métricas

`olt_query_latest`: um valor tipado (nunca saída crua) por (OLT, consulta, parâmetros). Ordem de escrita: (owner_epoch, observed_at); um valor mais velho ou de dono anterior
não regride o cache. `olt_metric_samples`: série (temperatura por placa), retenção de 400 dias (a poda entra com as rotinas do Edge, que são quem produz volume).

Revision ID: 0031
Revises: 0030
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE olt_query_latest (
          tenant_id uuid NOT NULL,
          olt_id uuid NOT NULL,
          query_id text NOT NULL CHECK (query_id ~ '^[a-z]+(\\.[a-z]+)+$'),
          params_key text NOT NULL CHECK (params_key ~ '^[a-z0-9=,]{{0,40}}$'),
          data jsonb NOT NULL,
          observed_at timestamptz NOT NULL,
          received_at timestamptz NOT NULL DEFAULT now(),
          owner_epoch integer NOT NULL CHECK (owner_epoch >= 1),
          seq bigint,
          source text NOT NULL CHECK (source IN ('job', 'routine')),
          version bigint NOT NULL DEFAULT 1,
          PRIMARY KEY (tenant_id, olt_id, query_id, params_key),
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id) ON DELETE CASCADE
        );
        ALTER TABLE olt_query_latest ENABLE ROW LEVEL SECURITY;
        ALTER TABLE olt_query_latest FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON olt_query_latest USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON olt_query_latest TO fibercore_app;
        GRANT UPDATE (data, observed_at, received_at, owner_epoch, seq, source, version) ON olt_query_latest TO fibercore_app;

        CREATE TABLE olt_metric_samples (
          tenant_id uuid NOT NULL,
          olt_id uuid NOT NULL,
          metric text NOT NULL CHECK (metric ~ '^[a-z][a-z0-9_]{{1,40}}$'),
          scope_key text NOT NULL CHECK (scope_key ~ '^[a-z0-9=,]{{0,40}}$'),
          at timestamptz NOT NULL,
          value numeric NOT NULL,
          PRIMARY KEY (tenant_id, olt_id, metric, scope_key, at),
          FOREIGN KEY (tenant_id, olt_id) REFERENCES olts(tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX olt_metric_samples_at ON olt_metric_samples (at);
        ALTER TABLE olt_metric_samples ENABLE ROW LEVEL SECURITY;
        ALTER TABLE olt_metric_samples FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON olt_metric_samples USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT, INSERT ON olt_metric_samples TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS olt_metric_samples; DROP TABLE IF EXISTS olt_query_latest;")
