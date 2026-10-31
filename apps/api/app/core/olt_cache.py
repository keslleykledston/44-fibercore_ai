"""Cache primeiro das consultas à OLT (ADR-0032): o último resultado TIPADO de cada consulta, com a idade, e a série de métricas.

Só entra aqui o que já passou por `olt_query.check_result` (a saída crua do equipamento nunca chega à nuvem). A hora do dado é a hora da NUVEM ao receber o resultado
do Edge (`observed_at`), nunca a hora da OLT, que vive só dentro de `data`. Um valor só substitui outro de (owner_epoch, observed_at) maior ou igual: um resultado de dono
anterior, ou de uma pergunta mais antiga que a guardada (resultado atrasado), não regride o cache."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, text

DEFAULT_TTL = timedelta(minutes=15)
# how long a cached value answers a request without asking the equipment again (ADR-0032 item 2); what changes little lives longer
TTL: dict[str, timedelta] = {
    "olt.version": timedelta(hours=1), "olt.board": timedelta(hours=1), "olt.time": timedelta(minutes=2),
    "olt.sync": timedelta(minutes=15), "olt.temperature": timedelta(minutes=15),
}
REFRESH_PER_HOUR = 3   # forcing the equipment to be asked again has its own quota, per OLT


def ttl(query_id: str) -> timedelta:
    return TTL.get(query_id, DEFAULT_TTL)


def params_key(params: dict) -> str:
    """Canonical key of the integers of the scope: '' (global), 's=3', 's=1,p=0', 's=1,p=0,o=9. Only the fields a scope takes are in `params`."""
    parts = [f"{k}={params[f]}" for k, f in (("s", "slot"), ("p", "port"), ("o", "ont")) if f in params]
    return ",".join(parts)


def store_latest(conn: Connection, tenant_id: UUID, olt_id: UUID, query_id: str, key: str, data: dict, owner_epoch: int, asked_at: datetime, source: str = "job") -> bool:
    """Upsert; False when a value of an equal-or-newer (owner_epoch, asked_at) is already there: a late result of an OLDER question never renews the age of the cache."""
    r = conn.execute(
        text("INSERT INTO olt_query_latest (tenant_id, olt_id, query_id, params_key, data, observed_at, asked_at, owner_epoch, source) "
             "VALUES (:t, :o, :q, :k, CAST(:d AS jsonb), now(), :a, :e, :s) "
             "ON CONFLICT (tenant_id, olt_id, query_id, params_key) DO UPDATE SET data = EXCLUDED.data, observed_at = EXCLUDED.observed_at, asked_at = EXCLUDED.asked_at, received_at = now(), "
             "owner_epoch = EXCLUDED.owner_epoch, source = EXCLUDED.source, version = olt_query_latest.version + 1 "
             "WHERE (EXCLUDED.owner_epoch, EXCLUDED.asked_at) >= (olt_query_latest.owner_epoch, olt_query_latest.asked_at) RETURNING version"),
        {"t": tenant_id, "o": olt_id, "q": query_id, "k": key, "d": json.dumps(data), "a": asked_at, "e": owner_epoch, "s": source}).first()
    return r is not None


def latest(conn: Connection, olt_id: UUID, query_id: str, key: str) -> dict | None:
    r = conn.execute(
        text("SELECT l.data, l.observed_at, l.received_at, l.owner_epoch, l.source, l.version, EXTRACT(EPOCH FROM (now() - l.observed_at)) AS age FROM olt_query_latest l "
             "WHERE l.olt_id = :o AND l.query_id = :q AND l.params_key = :k "
             "AND l.owner_epoch = (SELECT owner_epoch FROM olts WHERE id = l.olt_id)"), {"o": olt_id, "q": query_id, "k": key}).first()
    if r is None:
        return None
    age = max(0, int(r.age))
    limit = int(ttl(query_id).total_seconds())
    data = r.data if isinstance(r.data, dict) else json.loads(r.data)
    return {"data": data, "observed_at": r.observed_at.isoformat(), "age_seconds": age, "ttl_seconds": limit, "stale": age > limit, "source": r.source}


def samples_of(query_id: str, data: dict) -> list[tuple[str, str, float]]:
    """(metric, scope_key, value) of a typed result that is a series."""
    if query_id == "olt.temperature":
        return [("board_temp_c", f"s={x['slot']}", float(x["celsius"])) for x in data.get("boards", [])]
    return []


def store_samples(conn: Connection, tenant_id: UUID, olt_id: UUID, query_id: str, data: dict) -> int:
    n = 0
    for metric, scope, value in samples_of(query_id, data):
        n += conn.execute(
            text("INSERT INTO olt_metric_samples (tenant_id, olt_id, metric, scope_key, at, value) VALUES (:t, :o, :m, :s, now(), :v) ON CONFLICT DO NOTHING"),
            {"t": tenant_id, "o": olt_id, "m": metric, "s": scope, "v": value}).rowcount
    return n
