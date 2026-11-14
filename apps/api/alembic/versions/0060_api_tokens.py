"""Tokens de API por organização (ADR-0051 D1, fatia F1): `api_tokens` e a busca pelo hash feita só por uma função.

`api_tokens (tenant_id, id, name, prefix, token_hash, permissions text[], created_by, created_at, expires_at, last_used_at, revoked_at, revoked_by)`. O segredo (`fcat_<8>_<43>`) é
mostrado UMA vez; o banco guarda só o SHA-256. As permissões do token são uma lista FECHADA de leitura (`CHECK` abaixo, e a API valida de novo): nenhum token escreve, nenhum lê cliente final,
equipe, auditoria de pessoas nem segredo.

* A aplicação lê as colunas de exibição (NUNCA `token_hash`), insere, e só atualiza `revoked_at/revoked_by`: nunca apaga.
* Autenticar é achar o token SEM conhecer a organização: `app_api_token_lookup(p_hash)` (`SECURITY DEFINER`, `EXECUTE` só à aplicação) lê pela política `token_lookup` do dono (só linhas ainda
  vivas: não revogadas e não vencidas), devolve organização/id/permissões e carimba `last_used_at` no máximo 1 vez por minuto. Token revogado ou vencido não aparece: a resposta é a mesma de "não existe".
Reversível: remove a função e a tabela. Revision ID: 0060  Revises: 0059
"""
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

# the closed read-only list (keep in step with API_TOKEN_PERMISSIONS in app/core/api_tokens.py; a test compares the two)
ALLOWED = ("inventory:read", "incidents:read", "fleet:read", "discovery:read", "diagnostics:quality_read")
ALLOWED_SQL = ", ".join(f"'{p}'" for p in ALLOWED)

LOOKUP = """
CREATE FUNCTION app_api_token_lookup(p_hash bytea) RETURNS TABLE (tenant_id uuid, id uuid, permissions text[], expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r record; prev text;
BEGIN
  SELECT t.tenant_id AS tid, t.id AS tid2, t.permissions AS perms, t.expires_at AS exp, t.last_used_at AS lu INTO r
    FROM api_tokens t WHERE t.token_hash = p_hash AND t.revoked_at IS NULL AND t.expires_at > now();
  IF NOT FOUND THEN RETURN; END IF;
  IF r.lu IS NULL OR r.lu < now() - interval '1 minute' THEN
    prev := current_setting('app.tenant_id', true);
    PERFORM set_config('app.tenant_id', r.tid::text, true);
    UPDATE api_tokens u SET last_used_at = now() WHERE u.tenant_id = r.tid AND u.id = r.tid2;
    PERFORM set_config('app.tenant_id', COALESCE(prev, ''), true);
  END IF;
  tenant_id := r.tid; id := r.tid2; permissions := r.perms; expires_at := r.exp;
  RETURN NEXT;
END $$;
REVOKE ALL ON FUNCTION app_api_token_lookup(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_api_token_lookup(bytea) TO fibercore_app;
"""


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE api_tokens (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          name text NOT NULL CHECK (length(btrim(name)) BETWEEN 2 AND 60 AND name !~ '[[:cntrl:]]'),
          prefix text NOT NULL CHECK (prefix ~ '^[A-Za-z0-9]{{8}}$'),
          token_hash bytea NOT NULL UNIQUE CHECK (length(token_hash) = 32),
          permissions text[] NOT NULL CHECK (cardinality(permissions) BETWEEN 1 AND 10 AND permissions <@ ARRAY[{ALLOWED_SQL}]::text[]),
          created_by uuid NOT NULL REFERENCES users_global(id),
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          last_used_at timestamptz,
          revoked_at timestamptz,
          revoked_by uuid REFERENCES users_global(id),
          PRIMARY KEY (tenant_id, id),
          CONSTRAINT api_token_window CHECK (expires_at > created_at AND expires_at <= created_at + interval '366 days')
        );
        ALTER TABLE api_tokens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE api_tokens FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON api_tokens USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT (tenant_id, id, name, prefix, permissions, created_by, created_at, expires_at, last_used_at, revoked_at, revoked_by) ON api_tokens TO fibercore_app;
        GRANT INSERT (tenant_id, id, name, prefix, token_hash, permissions, created_by, expires_at) ON api_tokens TO fibercore_app;
        GRANT UPDATE (revoked_at, revoked_by) ON api_tokens TO fibercore_app;
        DO $$ BEGIN
          EXECUTE format($p$CREATE POLICY token_lookup ON api_tokens FOR SELECT TO %I USING (revoked_at IS NULL AND expires_at > now())$p$, current_user);
        END $$;
        """
    )
    op.execute(LOOKUP)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_api_token_lookup(bytea)")
    op.execute("DROP TABLE IF EXISTS api_tokens")
