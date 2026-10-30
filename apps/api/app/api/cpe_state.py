"""CPE state (WAN link/connection, uptime, Wi-Fi radio) read from the ACS cache by the Edge: ingestion and read.
READ-ONLY toward the network: nothing here sends anything to a device. Only a CLOSED list of metrics with typed values is accepted (the same
list the Edge validates against), so SSIDs, PSKs, PPPoE users and MACs cannot ride along; `captured_at` is the device-side time and is what
rules must reason about."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.inventory import CpeBinding, _bound_edge, _check_observed

router = APIRouter()

# The scope is closed PER METRIC (fixed word + numeric instances): a generic pattern would let free text such as an SSID in ("myhome/1").
# Kept textually identical to the Edge's cloudScopeByMetric (params_test.go) and to the CHECK of migration 0019; a test compares them.
SCOPE_RE = {
    "wan_link_status": re.compile(r"^link/[0-9]{1,3}$"),
    "wan_connection_status": re.compile(r"^(ppp|ip)(/[0-9]{1,3}){1,2}$"),
    "uptime_seconds": re.compile(r"^((ppp|ip)(/[0-9]{1,3}){1,2}|device/0)$"),
    "wifi_radio_enabled": re.compile(r"^radio/[0-9]{1,3}$"),
    "wifi_channel": re.compile(r"^radio/[0-9]{1,3}$"),
}
_CONN = ("Unconfigured", "Connecting", "Connected", "PendingDisconnect", "Disconnecting", "Disconnected",  # TR-098 WANxxxConnection
         "Up", "Down", "Dormant", "NotPresent", "LowerLayerDown", "Error", "Unknown")  # TR-181 PPP interface
# metric -> ("enum", accepted values) | ("int", min, max). Mirrors agents/edge/internal/nbi/params.go (a test checks it).
METRICS: dict[str, tuple] = {
    "wan_link_status": ("enum", frozenset({"Up", "Down", "Initializing", "Unavailable"})),
    "wan_connection_status": ("enum", frozenset(_CONN)),
    "uptime_seconds": ("int", 0, 1 << 31),
    "wifi_radio_enabled": ("enum", frozenset({"Enabled", "Disabled"})),  # the Edge reports state words, not JSON booleans
    "wifi_channel": ("int", 0, 196),
}
MetricName = Literal["wan_link_status", "wan_connection_status", "uptime_seconds", "wifi_radio_enabled", "wifi_channel"]
DISPLAY_FRESH_FOR = timedelta(hours=1)  # a display hint only; each rule decides how old is too old for it


class MetricIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: MetricName
    scope: str = Field(max_length=32)
    value: StrictStr | StrictInt | StrictBool
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def _captured(cls, v: datetime) -> datetime:
        return _check_observed(v)

    @model_validator(mode="after")
    def _typed(self) -> MetricIn:
        if not SCOPE_RE[self.name].fullmatch(self.scope):
            raise ValueError(f"scope is not valid for {self.name}")
        spec = METRICS[self.name]
        v = self.value
        if spec[0] == "enum":
            ok = isinstance(v, str) and v in spec[1]
        else:
            ok = isinstance(v, int) and not isinstance(v, bool) and spec[1] <= v <= spec[2]
        if not ok:
            raise ValueError(f"value is not valid for {self.name}")
        return self


class StateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binding: CpeBinding
    metrics: list[MetricIn] = Field(min_length=1, max_length=64)


class CpeStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: UUID
    observed_at: datetime
    states: list[StateIn] = Field(max_length=500)

    _obs = field_validator("observed_at")(_check_observed)


@router.post("/v1/edge/cpe-state", status_code=202)
def ingest_cpe_state(
    body: CpeStateSnapshot, p: Principal = Depends(require("inventory:write")), conn: Connection = TENANT_CONN
) -> dict:
    _bound_edge(p, body.edge_id)
    if not body.states:
        return {"status": "accepted", "cpes": 0, "metrics": 0, "unknown": 0}
    bound = {
        (r.connector_id, r.protocol, r.external_id): (r.id, r.edge_id)
        for r in conn.execute(
            text("SELECT b.connector_id, b.protocol, b.external_id, c.id, c.edge_id FROM cpe_protocol_bindings b JOIN cpes c "
                 "ON c.tenant_id = b.tenant_id AND c.id = b.cpe_id WHERE b.tenant_id = :t AND b.external_id = ANY(:x)"),
            {"t": p.tenant_id, "x": [s.binding.external_id for s in body.states]},
        )
    }
    rows: list[dict] = []
    unknown = 0
    cpes: set = set()
    for s in body.states:
        hit = bound.get((s.binding.connector_id, s.binding.protocol, s.binding.external_id))
        if hit is None or hit[1] != body.edge_id:  # unknown, or another edge's CPE: indistinguishable on purpose (no existence oracle)
            unknown += 1
            continue
        cpes.add(hit[0])
        for m in s.metrics:
            rows.append({"t": p.tenant_id, "c": hit[0], "m": m.name, "s": m.scope, "v": json.dumps(m.value), "ca": m.captured_at,
                         "o": body.observed_at})
    if rows:
        conn.execute(  # STRICTLY newer device time wins: a replay or an older read never overwrites a newer observation
            text("INSERT INTO cpe_state (tenant_id, cpe_id, metric, scope, value, captured_at, observed_at) "
                 "VALUES (:t,:c,:m,:s,CAST(:v AS jsonb),:ca,:o) ON CONFLICT (tenant_id, cpe_id, metric, scope) DO UPDATE SET "
                 "value = EXCLUDED.value, captured_at = EXCLUDED.captured_at, observed_at = EXCLUDED.observed_at, received_at = now() "
                 "WHERE cpe_state.captured_at < EXCLUDED.captured_at"),
            rows,
        )
    return {"status": "accepted", "cpes": len(cpes), "metrics": len(rows), "unknown": unknown}


@router.get("/v1/cpes/{cpe_id}/state")
def cpe_state(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    if conn.execute(text("SELECT 1 FROM cpes WHERE id = :i"), {"i": cpe_id}).first() is None:
        raise HTTPException(404, "cpe not found")
    now = datetime.now(UTC)
    out = []
    for r in conn.execute(
        text("SELECT metric, scope, value, captured_at, received_at FROM cpe_state WHERE cpe_id = :i ORDER BY metric, scope"), {"i": cpe_id}
    ):
        age = now - r.captured_at
        out.append({"metric": r.metric, "scope": r.scope, "value": r.value, "captured_at": r.captured_at, "received_at": r.received_at,
                    "age_seconds": max(0, int(age.total_seconds())), "fresh": age <= DISPLAY_FRESH_FOR})
    return {"cpe_id": cpe_id, "source": "acs_cache", "metrics": out}
