"""Read-only queries of the OLT's CLI as a job (`olt_query`, ADR-0029): the cloud side of the contract.

The cloud knows the SAME typed catalog as the Edge (agents/edge/internal/olt/query.go; a test compares the two so they cannot drift), accepts only a closed
intent per query (`query_id` plus exactly the integer fields of that query's scope), and stamps the OLT identity and the catalog version into it, so that
the intent hash, the audit and the signed envelope all cover them. What this module does NOT do: reach any equipment. The channel that carries a query
to the Edge's CLI session (persistent queue, ownership lease, parsers) is the Edge side of ADR-0029 and is still missing: `EDGE_SUPPORT` stays False
until it exists and is tested, so nothing is dispatched and the tenant flag cannot be turned on.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
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
    Query("olt.time", "Hora e fuso da OLT", "global", False),
    Query("olt.board", "Placas e estado", "global", True),
    Query("olt.alarm.active", "Alarmes ativos", "global", False),
    Query("olt.alarm.history", "Histórico de alarmes (lista)", "global", False),
    Query("olt.event.history", "Histórico de eventos (lista)", "global", False),
    Query("olt.autofind", "ONTs detectadas e não confirmadas", "global", False),
    Query("olt.temperature", "Temperatura", "global", False),
    Query("olt.sync", "Sincronismo de controladoras", "global", False),
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
ROLLOUT: frozenset[str] = frozenset({"olt.version", "olt.board"})

# the Edge side of the channel (queue, lease, parsers) does not exist yet: nothing is dispatched and the tenant flag cannot be turned on while False
EDGE_SUPPORT = False

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
