"""Read-only queries of the OLT's CLI as a job (`olt_query`, ADR-0029): the cloud side of the contract.

The cloud knows the SAME typed catalog as the Edge (agents/edge/internal/olt/query.go; a test compares the two so they cannot drift), accepts only a closed
intent per query (`query_id` plus exactly the integer fields of that query's scope), and stamps the OLT identity and the catalog version into it, so that
the intent hash, the audit and the signed envelope all cover them. What this module does NOT do: reach any equipment. The channel that carries a query
to the Edge's CLI session (durable queue, ownership lease, typed parsers) exists on the Edge side (agents/edge, ADR-0029 slices 2-4) and was rehearsed in
simulators; `EDGE_SUPPORT` is True from slice 5, but nothing is offered or dispatched until the tenant flag `olt_query` is turned on (owner CLI `feature-set`),
and each OLT also needs `olt_query_enabled` + `cloud_id` in its Edge's configuration.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

Scope = Literal["global", "slot", "pon", "onu"]
# the integer fields each scope takes, and nothing else (a missing or extra field is refused, never ignored)
SCOPE_FIELDS: dict[str, tuple[str, ...]] = {"global": (), "slot": ("slot",), "pon": ("slot", "port"), "onu": ("slot", "port", "ont")}
LIMITS = {"slot": 17, "port": 15, "ont": 127}  # inclusive upper bounds, lower bound 0 (MA5608T, ADR-0029 item 2)


@dataclass(frozen=True)
class Query:
    id: str
    title: str
    scope: Scope
    validated: bool  # proven on the real OLT with a sanitised fixture; the others need a supervised capture first (ADR-0029 item 6)


# Same ids, scopes and flags as agents/edge/internal/olt/query.go (tests/test_olt_query.py compares them).
CATALOG: tuple[Query, ...] = (
    Query("olt.version", "Software, patch e uptime", "global", True),
    Query("olt.time", "Hora e fuso da OLT", "global", True),
    Query("olt.board", "Placas e estado", "global", True),
    Query("olt.alarm.active", "Alarmes ativos", "global", False),
    Query("olt.alarm.history", "Histórico de alarmes (lista)", "global", False),
    Query("olt.event.history", "Histórico de eventos (lista)", "global", False),
    Query("olt.autofind", "ONTs detectadas e não confirmadas", "global", False),
    Query("olt.temperature", "Temperatura", "global", True),
    Query("olt.sync", "Sincronismo de controladoras", "global", True),
    Query("slot.board", "Detalhe da placa", "slot", False),
    Query("slot.cpu", "CPU da placa", "slot", False),
    Query("slot.mem", "Memória da placa", "slot", False),
    Query("pon.ont.summary", "Contagem de ONTs da PON", "pon", False),
    Query("pon.ont.info", "ONTs da PON", "pon", True),
    Query("pon.ont.optical", "Óptica das ONTs da PON", "pon", True),
    Query("pon.port.info", "Informação da porta PON", "pon", False),
    Query("pon.port.state", "Estado da porta PON", "pon", False),
    Query("pon.ont.autofind", "ONTs não confirmadas na PON", "pon", False),
    Query("onu.info", "ONT", "onu", False),
    Query("onu.optical", "Óptica da ONT", "onu", False),
    Query("onu.register", "Registro e causa da última queda", "onu", False),
    Query("onu.alarm", "Alarmes da ONT", "onu", False),
    Query("onu.version", "Versão da ONT", "onu", False),
    Query("onu.capability", "Capacidades da ONT", "onu", False),
    Query("onu.eth", "Portas Ethernet da ONT", "onu", False),
)
BY_ID = {q.id: q for q in CATALOG}

# ADR-0029 item 7: the rollout is by steps. Only these are offered by the cloud now (the global, already validated ones); the PON ones come after a
# supervised rehearsal in the LAB. Being in the catalog is not being offered.
ROLLOUT: frozenset[str] = frozenset({"olt.version", "olt.board", "olt.time", "olt.sync", "olt.temperature"})

# the Edge side of the channel (queue, lease, parsers) exists; the tenant flag and the Edge's own configuration still decide whether anything runs
EDGE_SUPPORT = True

# an olt_query envelope is short-lived on its own: a copy that waits in transit or in a queue dies in minutes
# the Edge accepts at most 20 min (+1 s). Worst wait: a request right after a window waits the 15 min interval, then the ~3 min collection
# before the queries run (about 18.5 min)
ENVELOPE_TTL = timedelta(minutes=20)
JOB_TTL = timedelta(minutes=22)       # the job outlives its envelope slightly, so the result of a query run at the very end is still accepted

# quota (ADR-0029 item 5): requests per rolling hour. The Edge has its own, stricter, budget per OLT (5 per session, 20 per hour).
USER_PER_HOUR = 10
TENANT_PER_HOUR = 60
OLT_PER_HOUR = 20   # the same hourly budget the Edge keeps per OLT: asking for more here would only queue what the Edge will expire


def catalog_version() -> str:
    """Hash of the catalog both sides must hold; the Edge refuses an intent made against another one."""
    blob = "\n".join(f"{q.id}|{q.scope}|{int(q.validated)}" for q in CATALOG)
    return hashlib.sha256(blob.encode()).hexdigest()


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check_params(query_id: str, raw: dict) -> dict:
    """The client's part of the intent: exactly the fields of the query's scope, each a bounded integer. Raises ValueError with a stable code."""
    q = BY_ID.get(query_id)
    if q is None:
        raise ValueError("unknown_query")
    want = SCOPE_FIELDS[q.scope]
    if set(raw) != set(want):
        raise ValueError("fields_do_not_match_scope")
    for f in want:
        if not _is_int(raw[f]) or not 0 <= raw[f] <= LIMITS[f]:
            raise ValueError("parameter_out_of_range")
    return {f: raw[f] for f in want}


def build_intent(olt_id: UUID, raw: dict) -> dict:
    """The closed intent that is hashed, audited and signed: {query_id, olt_ref, catalog_version} + the scope's integers."""
    if not isinstance(raw, dict) or not isinstance(raw.get("query_id"), str):
        raise ValueError("query_id_required")
    rest = {k: v for k, v in raw.items() if k != "query_id"}
    return {"query_id": raw["query_id"], **check_params(raw["query_id"], rest), "olt_ref": str(olt_id), "catalog_version": catalog_version()}


# ---- typed results (ADR-0029 item 4): the Edge sends a closed object per query, never device output; the Cloud checks the shape again before storing it
_PRODUCT = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,23}$")
_RELEASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{1,39}$")
_BOARD = re.compile(r"^[A-Za-z0-9]{3,20}$")
_STATUS = re.compile(r"^[A-Za-z_]{3,24}$")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")


def _is_slot(v) -> bool:
    return _is_int(v) and 0 <= v <= LIMITS["slot"]


def check_result(query_id: str, data) -> bool:
    """True only for the exact typed shape of a query that has a parser; anything else (extra keys, wrong types, free text) is refused."""
    if not isinstance(data, dict):
        return False
    if query_id == "olt.version":
        return (set(data) == {"product", "version", "patch", "uptime_seconds"} and isinstance(data["product"], str) and bool(_PRODUCT.match(data["product"]))
                and isinstance(data["version"], str) and bool(_RELEASE.match(data["version"])) and isinstance(data["patch"], str)
                and bool(_RELEASE.match(data["patch"])) and _is_int(data["uptime_seconds"]) and 0 <= data["uptime_seconds"] <= 10**9)
    if query_id == "olt.board":
        b, e = data.get("boards"), data.get("empty_slots")
        if set(data) != {"boards", "empty_slots"} or not isinstance(b, list) or not isinstance(e, list) or len(b) + len(e) > LIMITS["slot"] + 1:
            return False
        slots = []
        for x in b:
            if not (isinstance(x, dict) and set(x) == {"slot", "name", "status"} and _is_slot(x["slot"]) and isinstance(x["name"], str)
                    and _BOARD.match(x["name"]) and isinstance(x["status"], str) and _STATUS.match(x["status"])):
                return False
            slots.append(x["slot"])
        slots += list(e)
        return all(_is_slot(s) for s in slots) and len(set(slots)) == len(slots) and len(b) > 0
    if query_id == "olt.time":
        t = data.get("time")
        if set(data) != {"time"} or not isinstance(t, str) or not _TIME.match(t):
            return False
        try:
            return 2000 <= datetime.fromisoformat(t).year <= 2100
        except ValueError:
            return False
    if query_id == "olt.sync":
        return data == {"standby": "absent_or_fault"}
    if query_id == "olt.temperature":
        rows = data.get("boards")
        if set(data) != {"boards"} or not isinstance(rows, list) or not 1 <= len(rows) <= LIMITS["slot"] + 1:
            return False
        for x in rows:
            if not (isinstance(x, dict) and set(x) == {"slot", "name", "celsius"} and _is_slot(x["slot"]) and isinstance(x["name"], str) and _BOARD.match(x["name"])
                    and _is_int(x["celsius"]) and -40 <= x["celsius"] <= 150):
                return False
        return len({x["slot"] for x in rows}) == len(rows)
    return False
