"""RBAC inventory and the generated matrix (ADR-0031). Pure introspection of the real app: no database, no network."""
from __future__ import annotations

from fastapi.routing import APIRoute

from app.api import deps
from app.core.permissions import CATALOG
from app.core.security import ROLE_PERMISSIONS

ROLE_ORDER = ["isp_admin", "engineer", "noc_n2", "noc_n1", "support", "auditor", "platform_support", "edge_agent"]


def _collect(routes, out: list) -> None:
    """Walks the effective route tree: included routers (any depth), nested routers; a Mount is refused (an unknown sub-application cannot be inventoried)."""
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        elif hasattr(r, "original_router"):
            _collect(r.original_router.routes, out)
        elif hasattr(r, "routes") and type(r).__name__ in ("APIRouter", "_IncludedRouter"):
            _collect(r.routes, out)
        elif type(r).__name__ == "Mount":
            raise RuntimeError(f"mounted application at {getattr(r, 'path', '?')!r}: its routes cannot be inventoried; include a router instead")


def _routes() -> list[APIRoute]:
    from app.main import app

    out: list[APIRoute] = []
    _collect(app.routes, out)
    return out


def _deps(dependant, acc: list) -> None:
    for d in dependant.dependencies:
        acc.append(d.call)
        _deps(d, acc)


def _header_names(dependant) -> set[str]:
    names = {p.name.lower() for p in dependant.header_params}
    for d in dependant.dependencies:
        names |= _header_names(d)
    return names


def inventory() -> list[dict]:
    """One row per route and method. kind: 'require' (a catalog permission), 'principal' (a valid session, no permission), 'header_auth' (the handler
    authenticates the caller's OWN bearer token from the Authorization header), 'none' (no credentials checked by the route itself)."""
    rows = []
    for r in _routes():
        acc: list = []
        _deps(r.dependant, acc)
        perms = sorted({c.rbac_permission for c in acc if hasattr(c, "rbac_permission")})
        if perms:
            kind = "require"
        elif deps.get_principal in acc:
            kind = "principal"
        elif "authorization" in _header_names(r.dependant):
            kind = "header_auth"
        else:
            kind = "none"
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            rows.append({"method": m, "path": r.path, "kind": kind, "permissions": perms})
    return sorted(rows, key=lambda x: (x["path"], x["method"]))


def served_operations() -> set[tuple[str, str]]:
    """(method, path) of every operation the app serves according to its OWN OpenAPI schema: an independent source to compare the inventory with."""
    from app.main import app

    return {(m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops if m.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}}


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
        need = ", ".join(f"`{p}`" for p in r["permissions"]) if r["permissions"] else {
            "principal": "(sessão válida, sem permissão)", "header_auth": "(autentica o token da própria conta)", "none": "(pública ou usa credencial no corpo)"}[r["kind"]]
        out.append(f"| {r['method']} | `{r['path']}` | {need} |")
    return "\n".join(out) + "\n"
