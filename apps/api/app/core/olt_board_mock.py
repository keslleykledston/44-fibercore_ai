"""SYNTHETIC board inventory (`olt.board`, source 'mock') for a DEMO OLT, so the front-panel screen can be shown without equipment.

Two conditions, both checked in the SAME transaction as the write, and neither is a name: (1) the TENANT was created as a DEMONSTRATION tenant (`tenants.demo`, set only at creation
by `create-tenant --demo` and immutable afterwards: a trigger refuses any change);
(2) the OLT has no board inventory that came from the equipment (source `job`/`routine`): a real read is never overwritten. A real provider's tenant is refused whatever
its OLTs are called."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Connection, text

from app.core import olt_cache, olt_query


def store(conn: Connection, tenant_id: UUID | str, olt_name: str, slots: str = "0:H805GPFD,1:H805GPFD") -> list[int]:
    """Write the synthetic inventory. Raises ValueError with a stable message when refused."""
    conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    demo = conn.execute(text("SELECT demo FROM tenants WHERE id = :t"), {"t": str(tenant_id)}).scalar()
    if demo is not True:
        raise ValueError("refused: the board mock is only for the demonstration tenant")
    row = conn.execute(text("SELECT id, owner_epoch FROM olts WHERE tenant_id = :t AND name = :n FOR UPDATE"), {"t": str(tenant_id), "n": olt_name}).first()
    if row is None:
        raise ValueError("olt not found for this tenant")
    real = conn.execute(text("SELECT 1 FROM olt_query_latest WHERE olt_id = :o AND query_id = 'olt.board' AND source <> 'mock'"), {"o": row.id}).first()
    if real is not None:
        raise ValueError("refused: this OLT already has a board inventory read from the equipment; it is never overwritten")
    boards, taken = [], set()
    for part in [x for x in slots.split(",") if x]:
        m = re.fullmatch(r"([0-5]):([A-Z0-9]{3,20})", part)
        if not m:
            raise ValueError("--slots must look like 0:H805GPFD,1:H805GPFD")
        boards.append({"slot": int(m.group(1)), "name": m.group(2), "status": "Normal"})
        taken.add(int(m.group(1)))
    boards += [{"slot": 2, "name": "H801MCUD1", "status": "Active_normal"}, {"slot": 4, "name": "H801MPWE", "status": "Normal"}, {"slot": 5, "name": "H801MPWE", "status": "Normal"}]
    data = {"boards": sorted(boards, key=lambda b: b["slot"]), "empty_slots": [s for s in (0, 1) if s not in taken] + [3]}
    if not olt_query.check_result("olt.board", data):
        raise ValueError("the synthetic board inventory does not fit the typed shape")
    olt_cache.store_latest(conn, tenant_id, row.id, "olt.board", "", data, row.owner_epoch, datetime.now(UTC), source="mock")
    return sorted(taken)
