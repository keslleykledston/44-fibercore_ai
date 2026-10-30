"""RBAC inventory and the generated matrix (ADR-0031). Pure introspection of the real app: no database, no network."""
from __future__ import annotations

from fastapi.routing import APIRoute

from app.api import deps
from app.core.permissions import CATALOG
from app.core.security import ROLE_PERMISSIONS

ROLE_ORDER = ["isp_admin", "engineer", "noc_n2", "noc_n1", "support", "auditor", "platform_support", "edge_agent"]


def _routes() -> list[APIRoute]:
    from app.main import app

    out: list[APIRoute] = []
    for r in app.routes:
        if hasattr(r, "original_router"):
            out += [x for x in r.original_router.routes if isinstance(x, APIRoute)]
        elif isinstance(r, APIRoute):
            out.append(r)
    return out


def _deps(dependant, acc: list) -> None:
    for d in dependant.dependencies:
        acc.append(d.call)
        _deps(d, acc)


def inventory() -> list[dict]:
    """One row per route: method, path, kind ('require' | 'principal' | 'none') and the permissions it requires."""
    rows = []
    for r in _routes():
        acc: list = []
        _deps(r.dependant, acc)
        perms = sorted({c.rbac_permission for c in acc if hasattr(c, "rbac_permission")})
        kind = "require" if perms else ("principal" if deps.get_principal in acc else "none")
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            rows.append({"method": m, "path": r.path, "kind": kind, "permissions": perms})
    return sorted(rows, key=lambda x: (x["path"], x["method"]))


def render() -> str:
    roles = [r for r in ROLE_ORDER if r in ROLE_PERMISSIONS] + sorted(set(ROLE_PERMISSIONS) - set(ROLE_ORDER))
    out = ["# Matriz RBAC (gerada)", "",
           "> GERADA por `scripts/gen_rbac_matrix.py` a partir do catálogo (`app/core/permissions.py`), dos papéis (`app/core/security.py`) e das rotas reais. "
           "Não edite à mão: o teste `test_rbac_inventory.py` falha se este arquivo divergir do código. Decisão e plano: ADR-0031.", "",
           "## Permissões", "", "| Permissão | Risco | MFA recente | Escopável | O que permite |", "|---|---|---|---|---|"]
    for p in CATALOG.values():
        out.append(f"| `{p.name}` | {p.risk} | {'sim' if p.mfa_recent else 'não'} | {'sim' if p.scopable else 'não'} | {p.description} |")
    out += ["", "## Papéis × permissões", "", "| Permissão | " + " | ".join(f"`{r}`" for r in roles) + " |", "|---|" + "---|" * len(roles)]
    for p in CATALOG:
        out.append(f"| `{p}` | " + " | ".join("✔" if p in ROLE_PERMISSIONS[r] else "" for r in roles) + " |")
    inv = inventory()
    out += ["", "## Rotas × permissão", "", "| Método | Rota | Exige |", "|---|---|---|"]
    for r in inv:
        need = ", ".join(f"`{p}`" for p in r["permissions"]) if r["permissions"] else ("(sessão válida, sem permissão)" if r["kind"] == "principal" else "(pública ou autentica pelo próprio fluxo)")
        out.append(f"| {r['method']} | `{r['path']}` | {need} |")
    return "\n".join(out) + "\n"
