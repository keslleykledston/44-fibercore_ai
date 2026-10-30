"""The words people see for roles and capabilities (owner request 2026-10-30: "muita informação técnica, difícil de manusear").

The permission catalog stays the authority (app/core/permissions.py). This module only GROUPS its permissions into a few capabilities a non-technical
administrator understands, and gives each human role a name and a sentence. A test ties it to the catalog: every permission a human role holds belongs to
a capability, so a new permission cannot be added without deciding where people read about it."""
from __future__ import annotations

from app.core.security import ROLE_PERMISSIONS

# human roles, in the order people read them (most power first)
ROLE_INFO: dict[str, dict] = {
    "isp_admin": {
        "label": "Administrador", "summary": "Acesso total ao provedor, inclusive pessoas e funções.",
        "can": ["Ver a rede, os equipamentos e os clientes", "Pedir e aprovar mudanças em equipamentos", "Convidar, remover e mudar a função das pessoas"],
        "cannot": [],
    },
    "access_manager": {
        "label": "Gestor de acesso", "summary": "Cuida das pessoas e das funções. Não vê rede nem clientes.",
        "can": ["Convidar e remover pessoas", "Mudar a função de quase todos", "Ver a atividade da equipe"],
        "cannot": ["Ver a rede ou os clientes", "Mudar quem é Administrador"],
    },
    "engineer": {
        "label": "Engenheiro", "summary": "Opera a rede: vê clientes, pede mudanças e autoriza manobras de bancada.",
        "can": ["Ver a rede e os clientes", "Pedir mudanças em equipamentos", "Autorizar manobras de bancada"],
        "cannot": ["Aprovar mudanças", "Gerenciar pessoas"],
    },
    "noc_n2": {
        "label": "Operador NOC (nível 2)", "summary": "Acompanha a rede, trata incidentes e pede reinícios.",
        "can": ["Ver a rede e os clientes", "Reconhecer incidentes", "Pedir o reinício de um equipamento"],
        "cannot": ["Aprovar mudanças", "Gerenciar pessoas"],
    },
    "noc_n1": {
        "label": "Operador NOC (nível 1)", "summary": "Acompanha a rede e os incidentes. Só leitura.",
        "can": ["Ver a rede e os incidentes"], "cannot": ["Ver clientes", "Pedir mudanças"],
    },
    "support": {
        "label": "Atendimento", "summary": "Consulta rede e clientes para atender. Só leitura.",
        "can": ["Ver a rede", "Ver dados de clientes"], "cannot": ["Reconhecer incidentes", "Pedir mudanças"],
    },
    "auditor": {
        "label": "Auditor", "summary": "Lê o registro de atividade. Nada além disso.",
        "can": ["Ver o registro de atividade"], "cannot": ["Ver a rede ou os clientes", "Pedir mudanças"],
    },
}
HUMAN_ROLES = tuple(ROLE_INFO)
LABEL = {**{r: i["label"] for r, i in ROLE_INFO.items()}, "platform_support": "Suporte da plataforma (temporário)", "edge_agent": "Agente Edge"}

# (id, label, permissions): a role has the capability fully when it holds all of them, partly when it holds some
CAPABILITIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("network", "Ver a rede e os equipamentos", ("inventory:read", "edge:read")),
    ("customers", "Ver dados de clientes", ("customers:read",)),
    ("incidents", "Acompanhar incidentes", ("incidents:read",)),
    ("ack", "Reconhecer incidentes", ("incidents:ack",)),
    ("diagnose", "Rodar diagnósticos", ("diagnostics:run",)),
    ("olt_query", "Consultar a OLT (somente leitura)", ("olt_query:run",)),
    ("request", "Pedir mudanças em equipamentos", ("jobs:request", "devices:act:reboot_cpe", "devices:act:set_wifi_ssid")),
    ("approve", "Aprovar mudanças", ("jobs:approve",)),
    ("bench", "Autorizar manobras de bancada", ("bench:authorize",)),
    ("import", "Importar clientes e revisar vínculos", ("customers:import", "associations:review")),
    ("people", "Gerenciar pessoas e funções", ("members:manage", "members:mfa_reset", "platform:delegate")),
    ("audit", "Ver pessoas e atividade", ("members:read", "audit:read", "roles:read")),
]


def cell(role: str, perms: tuple[str, ...]) -> str:
    held = ROLE_PERMISSIONS.get(role, frozenset())
    n = sum(1 for p in perms if p in held)
    return "all" if n == len(perms) else ("some" if n else "none")


def matrix() -> dict[str, dict[str, str]]:
    return {r: {cid: cell(r, perms) for cid, _, perms in CAPABILITIES} for r in HUMAN_ROLES}


def uncovered() -> set[str]:
    """Permissions a human role holds that no capability mentions (the test wants this empty)."""
    mentioned = {p for _, _, perms in CAPABILITIES for p in perms}
    held = set().union(*(ROLE_PERMISSIONS[r] for r in HUMAN_ROLES))
    return held - mentioned - {"tenant:read", "jobs:read"}   # every member reads their own workspace and the job list: nothing to explain
