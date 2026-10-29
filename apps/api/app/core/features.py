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
