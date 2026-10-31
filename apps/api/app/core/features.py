"""Per-tenant feature flags (ADR-0023). The CODE owns the catalog and the defaults; the table only overrides them for one tenant.

Already-shipped capabilities default ON (turning a flag off is a kill switch); capabilities still being introduced default OFF, so a tenant
only sees them once the owner enables them. An unknown name is never "on".
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Connection, text

# name -> default. Keep the names in sync with docs/addenda/v2.2/GAP_ANALYSIS.md (FC22 ids in the comments).
FEATURES: dict[str, bool] = {
    "capability_registry": True,   # FC22-002 (shipped; flag = kill switch)
    "onu_cpe_links": False,        # FC22-004 / ADR-0021
    "customer_context": False,     # FC22-004
    "subscriber_360": False,       # FC22-005
    "diagnostic_engine": False,    # FC22-006
    # SD-001 (ADR-0025): nada disto tem endpoint ainda; ficam desligadas até o PR que implementa cada fatia.
    "olt_query": False,                       # ADR-0029: consultas somente leitura à OLT por job; só liga quando o canal do Edge existir (olt_query.EDGE_SUPPORT)
    "bench_writes": False,                    # ADR-0030: escritas homologadas SÓ para os alvos de bancada (gate de seis condições)
    "smart_diagnostics_jobs": False,          # SD-PR-03: diagnostic_jobs passivo/guiado (somente leitura)
    "smart_diagnostics_active_tests": False,  # bloqueada até ADR-SD-003
    "smart_diagnostics_remediation": False,   # propostas/aprovação; execução real só com HOMOLOGATED_WRITES
    "erp_hubsoft": False,                     # ADR-0033: conexão HubSoft (P0, somente leitura); só o dono liga, por provedor, depois de configurar o segredo no servidor
    "smart_diagnostics_copilot": False,       # bloqueada até ADR-0015 / ADR-SD-006
}


def resolve(conn: Connection, tenant_id: UUID) -> dict[str, dict]:
    """{feature: {enabled, source}} for every catalog feature; source = 'tenant' (override row) or 'default'."""
    rows = conn.execute(text("SELECT feature, enabled FROM tenant_features WHERE tenant_id = :t"), {"t": tenant_id})
    over = {r.feature: r.enabled for r in rows}
    return {f: {"enabled": over.get(f, d), "source": "tenant" if f in over else "default"} for f, d in FEATURES.items()}


def enabled(conn: Connection, tenant_id: UUID, feature: str) -> bool:
    if feature not in FEATURES:
        return False
    row = conn.execute(
        text("SELECT enabled FROM tenant_features WHERE tenant_id = :t AND feature = :f"), {"t": tenant_id, "f": feature}
    ).first()
    return row.enabled if row is not None else FEATURES[feature]


def ensure(conn: Connection, tenant_id: UUID, feature: str) -> None:
    if not enabled(conn, tenant_id, feature):
        raise HTTPException(403, "feature_disabled")
