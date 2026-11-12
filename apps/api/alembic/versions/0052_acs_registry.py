"""Cadastro de ACS por organização (ADR-0046 D2): `acs_connections`, `cpes.acs_id` e a função estreita com que o Edge informa o estado do SEU ACS

A nuvem só guarda o CADASTRO do ACS (nome, tipo, qual Edge o alcança, rótulo, ligado/desligado e `settings` sem segredo). A URL e o segredo do NBI continuam só no `config.json` do Edge (ADR-0041 D3).

* `kind` NÃO é enum no banco: o registro de tipos (`ACS_KINDS`) vive no código (`app/core/acs.py`); acrescentar ou trocar um tipo não exige migração. O banco só garante a FORMA (`^[a-z][a-z0-9_]{1,31}$`).
* Identidade estável: `id` imutável; `name` é só rótulo (único sem diferenciar caixa por `(tenant_id, edge_id)`), renomeável sem perder o estado. `kind`, `edge_id`, `tenant_id`, `id` e `created_at` nunca mudam
  (nem por GRANT, que não existe, nem por gatilho `acs_connections_guard`, que vale também para a dona).
* No máximo UM ACS ATIVO por Edge: índice único parcial `(tenant_id, edge_id) WHERE enabled` (o Edge suporta uma única `nbi_url`). Desativar libera a vaga.
* Isolamento: RLS forçada por tenant; FK composta `(tenant_id, edge_id)`: o ACS é de UM Edge da MESMA organização.
* Quem escreve o quê (decisão e justificativa): a role da aplicação tem GRANT de coluna só no que o USUÁRIO edita (name, label, enabled, settings, updated_at; INSERT sem as colunas de estado). `last_seen_at`, `last_ok_at`,
  `device_count` e `last_error_code` NÃO têm GRANT: nenhuma rota de usuário consegue gravá-los. O ÚNICO escritor é a função SECURITY DEFINER estreita `app_acs_edge_report(acs, edge, kind, ok, device_count, error_code)`,
  que só mexe no ACS DAQUELE Edge, do tenant da sessão (RLS forçada), com o `kind` cadastrado, e devolve `ignored` (sem revelar nada) para qualquer outro. Escolhi função em vez de GRANT de coluna porque o padrão do repo
  para o que só a rota do Edge toca (`app_olt_edge_report`, `app_secret_delivery_blob`) já é função estreita, e porque a regra "só o ACS do PRÓPRIO Edge, do kind certo" fica no banco, não em cada rota; um GRANT de coluna
  deixaria a role da aplicação gravar o estado de QUALQUER ACS do tenant.
* `cpes.acs_id` (nulo): o ACS ativo do Edge dono do CPE quando o CPE foi lido. FK composta `(tenant_id, acs_id, edge_id)` -> `acs_connections(tenant_id, id, edge_id)`: o banco recusa um CPE ligado a um ACS de OUTRO Edge
  (nunca inferido entre Edges). Sem backfill. Sem DELETE para a role da aplicação: ACS não se apaga, desativa-se.

Reversível. Revision ID: 0052  Revises: 0051
"""
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE acs_connections (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          name text NOT NULL CHECK (char_length(name) BETWEEN 2 AND 60 AND name = btrim(name)),
          kind text NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_]{{1,31}}$'),
          edge_id uuid NOT NULL,
          label text CHECK (label IS NULL OR char_length(label) BETWEEN 1 AND 80),
          enabled boolean NOT NULL DEFAULT true,
          settings jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(settings) = 'object' AND octet_length(settings::text) <= 2048),
          created_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          -- what the EDGE reported (written only by app_acs_edge_report)
          last_seen_at timestamptz,
          last_ok_at timestamptz,
          device_count integer CHECK (device_count IS NULL OR device_count BETWEEN 0 AND 10000000),
          last_error_code text CHECK (last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_]{{1,31}}$'),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (tenant_id, id, edge_id),     -- the target of cpes_acs_fk: a CPE can only point at an ACS of its own Edge
          FOREIGN KEY (tenant_id, edge_id) REFERENCES edges(tenant_id, id),
          CHECK (last_ok_at IS NULL OR (last_seen_at IS NOT NULL AND last_ok_at <= last_seen_at))
        );
        CREATE UNIQUE INDEX acs_connections_name_ci ON acs_connections (tenant_id, edge_id, lower(name));
        -- at most ONE active ACS per Edge (the Edge has a single nbi_url): the database decides, the API only answers 409 nicely
        CREATE UNIQUE INDEX acs_connections_one_active_per_edge ON acs_connections (tenant_id, edge_id) WHERE enabled;

        CREATE FUNCTION acs_connections_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (NEW.tenant_id, NEW.id, NEW.kind, NEW.edge_id, NEW.created_at) IS DISTINCT FROM (OLD.tenant_id, OLD.id, OLD.kind, OLD.edge_id, OLD.created_at) THEN
            RAISE EXCEPTION 'acs_connections: id, kind, edge and tenant are immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER acs_connections_guard BEFORE UPDATE ON acs_connections FOR EACH ROW EXECUTE FUNCTION acs_connections_guard();

        ALTER TABLE acs_connections ENABLE ROW LEVEL SECURITY;
        ALTER TABLE acs_connections FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON acs_connections USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        -- the application role: reads everything; writes ONLY what a person edits. No DELETE, no grant on the Edge-reported columns.
        GRANT SELECT ON acs_connections TO fibercore_app;
        GRANT INSERT (tenant_id, name, kind, edge_id, label, enabled, settings, created_by) ON acs_connections TO fibercore_app;
        GRANT UPDATE (name, label, enabled, settings, updated_at) ON acs_connections TO fibercore_app;

        -- the ONLY writer of last_seen_at / last_ok_at / device_count / last_error_code: the Edge's own report about ITS ACS of the session tenant.
        -- Returns 'changed' (first report, or the error code changed), 'same' or 'ignored' (unknown id, another Edge's, another tenant's, or another kind: all the same answer).
        CREATE FUNCTION app_acs_edge_report(p_acs uuid, p_edge uuid, p_kind text, p_ok boolean, p_device_count integer, p_error_code text) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE prev_err text; prev_seen timestamptz;
        BEGIN
          IF p_ok IS NULL OR (p_ok AND (p_error_code IS NOT NULL OR p_device_count IS NULL)) OR (NOT p_ok AND (p_error_code IS NULL OR p_device_count IS NOT NULL)) THEN
            RAISE EXCEPTION 'app_acs_edge_report: inconsistent report';
          END IF;
          SELECT last_error_code, last_seen_at INTO prev_err, prev_seen FROM acs_connections
           WHERE tenant_id = {cur_t} AND id = p_acs AND edge_id = p_edge AND kind = p_kind FOR UPDATE;
          IF NOT FOUND THEN
            RETURN 'ignored';
          END IF;
          UPDATE acs_connections
             SET last_seen_at = now(),
                 last_ok_at = CASE WHEN p_ok THEN now() ELSE last_ok_at END,
                 device_count = CASE WHEN p_ok THEN p_device_count ELSE device_count END,
                 last_error_code = p_error_code
           WHERE tenant_id = {cur_t} AND id = p_acs;
          RETURN CASE WHEN prev_seen IS NULL OR prev_err IS DISTINCT FROM p_error_code THEN 'changed' ELSE 'same' END;
        END $$;
        REVOKE ALL ON FUNCTION app_acs_edge_report(uuid, uuid, text, boolean, integer, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_acs_edge_report(uuid, uuid, text, boolean, integer, text) TO fibercore_app;

        -- the ACS a CPE was read through (the ACTIVE one of its Edge at the time of the read); NULL = no origin assigned. No backfill.
        ALTER TABLE cpes ADD COLUMN acs_id uuid;
        ALTER TABLE cpes ADD CONSTRAINT cpes_acs_fk FOREIGN KEY (tenant_id, acs_id, edge_id) REFERENCES acs_connections(tenant_id, id, edge_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE cpes DROP CONSTRAINT IF EXISTS cpes_acs_fk;
        ALTER TABLE cpes DROP COLUMN IF EXISTS acs_id;
        DROP FUNCTION IF EXISTS app_acs_edge_report(uuid, uuid, text, boolean, integer, text);
        DROP TABLE IF EXISTS acs_connections;
        DROP FUNCTION IF EXISTS acs_connections_guard();
        """
    )
