"""Operation catalog for the Capability Registry (ADR-0019).

Names are EXACTLY the operations of the job engine (app.api.jobs.OPERATIONS): nothing here is invented, no TR-181 path, OID or CLI command.
The catalog says which operations exist for a kind of device and over which protocols; the registry (table device_capabilities) says what is
known about them on a given vendor/model/firmware. No row = unknown/identified.
"""
from __future__ import annotations

from dataclasses import dataclass

PROTOCOLS_BY_KIND: dict[str, tuple[str, ...]] = {"cpe": ("tr069", "tr369"), "olt": ("olt",)}


@dataclass(frozen=True)
class CatalogEntry:
    operation: str
    protocol: str
    writes: bool


def catalog_for(kind: str, operations: dict) -> list[CatalogEntry]:
    """`operations` is app.api.jobs.OPERATIONS (passed in: one source of truth, no import cycle). Stable order."""
    out: list[CatalogEntry] = []
    for protocol in PROTOCOLS_BY_KIND[kind]:
        for name in sorted(n for n, o in operations.items() if o.target == kind):
            out.append(CatalogEntry(name, protocol, operations[name].writes))
    return out
