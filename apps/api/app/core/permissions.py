"""The ONE catalog of permissions (ADR-0031). Every `require("x:y")` and every entry of ROLE_PERMISSIONS must name a permission listed here; the
role × permission matrix in docs/security/RBAC_MATRIX.md is GENERATED from this file and the roles (scripts/gen_rbac_matrix.py), never edited by hand.

risk: R0 read of operational data; R1 read of sensitive/personal data or an import; R2 reversible action or a change of who can do what; R3 irreversible
or security-critical. mfa_recent: the action should be preceded by a recent second factor (enforced by a later delivery of ADR-0031; recorded now so the
catalog is complete). scopable: makes sense to restrict to a part of the network (OLT/site) if scope is ever adopted."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    name: str
    description: str
    risk: str  # R0..R3
    mfa_recent: bool = False
    scopable: bool = False


def _p(name: str, description: str, risk: str, mfa_recent: bool = False, scopable: bool = False) -> tuple[str, Permission]:
    return name, Permission(name, description, risk, mfa_recent, scopable)


CATALOG: dict[str, Permission] = dict([
    _p("tenant:read", "Ver o próprio provedor e seus dados básicos", "R0"),
    _p("inventory:read", "Ver OLTs, ONUs, CPEs, relatórios de rede e capacidades", "R0", scopable=True),
    _p("inventory:write", "Enviar inventário e estado (somente contas de serviço do Edge)", "R2"),
    _p("incidents:read", "Ver incidentes e o NOC", "R0", scopable=True),
    _p("incidents:ack", "Reconhecer um incidente", "R2", scopable=True),
    _p("customers:read", "Ver assinantes (dado pessoal; toda visualização é auditada)", "R1"),
    _p("customers:import", "Importar clientes do ERP", "R1", mfa_recent=True),
    _p("associations:review", "Revisar vínculos ONU↔cliente e ONU↔CPE", "R2"),
    _p("jobs:read", "Ver operações solicitadas", "R0"),
    _p("jobs:request", "Solicitar uma operação em equipamento", "R2", scopable=True),
    _p("jobs:approve", "Aprovar uma operação em equipamento", "R3", mfa_recent=True, scopable=True),
    _p("jobs:execute", "Executar operações aprovadas (somente contas de serviço do Edge)", "R3"),
    _p("diagnostics:run", "Rodar diagnósticos (somente leitura)", "R0", scopable=True),
    _p("members:read", "Ver os membros do provedor e o estado do MFA de cada um", "R1"),
    _p("members:manage", "Atribuir e alterar o papel dos membros (dentro do que o papel de quem atribui permite)", "R3", mfa_recent=True),
    _p("roles:read", "Ver os papéis do sistema e as permissões de cada um", "R0"),
    _p("members:mfa_reset", "Redefinir o MFA de outro membro", "R3", mfa_recent=True),
    _p("edge:read", "Ver os Edges do provedor", "R0"),
    _p("edge:heartbeat", "Enviar batimento (somente contas de serviço do Edge)", "R0"),
    _p("audit:read", "Ver o registro de auditoria", "R1"),
])
RISKS = ("R0", "R1", "R2", "R3")


def check_catalog(role_permissions: dict[str, frozenset[str]]) -> None:
    """Fail closed at import: a typo in a role, or a permission with no catalog entry, must stop the process instead of silently granting nothing/something."""
    for name, perm in CATALOG.items():
        if perm.name != name or perm.risk not in RISKS:
            raise RuntimeError(f"permission catalog entry {name!r} is malformed")
    for role, perms in role_permissions.items():
        unknown = perms - set(CATALOG)
        if unknown:
            raise RuntimeError(f"role {role!r} has permissions missing from the catalog: {sorted(unknown)}")


def require_known(permission: str) -> str:
    if permission not in CATALOG:
        raise RuntimeError(f"require({permission!r}): not in the permission catalog")
    return permission
