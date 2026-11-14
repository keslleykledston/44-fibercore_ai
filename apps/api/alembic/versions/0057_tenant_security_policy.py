"""Política de segurança por organização (ADR-0049, fatia D1): `tenant_security_policy`, MFA obrigatório por papel que SÓ APERTA o piso do ambiente.

`tenant_security_policy (tenant_id PK, mfa_required_roles text[], updated_by, updated_at)`. O piso é `MFA_REQUIRED_ROLES` + `ALWAYS_MFA_ROLES` do ambiente (código); a organização acrescenta papéis
a ele. A união é feita na LEITURA (`app/core/security_policy.py`): apagar a linha ou esvaziar a lista nunca baixa a organização abaixo do piso.
Só papéis humanos de organização (`CHECK`): nem `edge_agent` (conta de serviço) nem `platform_support` (delegação, já sempre com MFA).

RLS por organização; um membro lê a política das organizações a que pertence (precisa dela para saber se o MFA lhe é exigido ANTES de escolher uma organização, como já faz com as próprias
`tenant_memberships`). Escrita: só a role da aplicação, só as colunas da lista, nunca DELETE. Reversível: remove a tabela. Revision ID: 0057  Revises: 0056
"""
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

HUMAN_ROLES = ("isp_admin", "access_manager", "engineer", "noc_n2", "noc_n1", "support", "auditor")
ROLES_SQL = ", ".join(f"'{r}'" for r in HUMAN_ROLES)


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    cur_u = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE tenant_security_policy (
          tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
          mfa_required_roles text[] NOT NULL DEFAULT '{{}}' CHECK (mfa_required_roles <@ ARRAY[{ROLES_SQL}]::text[]),
          updated_by uuid REFERENCES users_global(id),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE tenant_security_policy ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_security_policy FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tenant_security_policy
          USING (tenant_id = {cur_t} OR EXISTS (SELECT 1 FROM tenant_memberships m WHERE m.tenant_id = tenant_security_policy.tenant_id AND m.user_id = {cur_u}))
          WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT ON tenant_security_policy TO fibercore_app;
        GRANT INSERT (tenant_id, mfa_required_roles, updated_by) ON tenant_security_policy TO fibercore_app;
        GRANT UPDATE (mfa_required_roles, updated_by, updated_at) ON tenant_security_policy TO fibercore_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_security_policy")
