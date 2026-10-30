from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

from app.core.settings import get_settings


def _url(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1) if dsn.startswith("postgresql://") else dsn


@lru_cache
def get_engine() -> Engine:
    dsn = get_settings().database_url
    if not dsn:
        raise RuntimeError("DATABASE_URL not configured")
    return create_engine(_url(dsn), pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def get_rbac_engine() -> Engine | None:
    """Connection of the dedicated `fibercore_rbac` role (ADR-0031); None when not configured, so the caller can fail closed."""
    dsn = get_settings().rbac_database_url
    return create_engine(_url(dsn), pool_pre_ping=True, pool_size=2, max_overflow=2) if dsn else None


def make_engine(dsn: str) -> Engine:
    return create_engine(_url(dsn), pool_pre_ping=True)


@contextmanager
def scoped_connection(
    engine: Engine, *, user_id: UUID | None = None, tenant_id: UUID | None = None
) -> Iterator[Connection]:
    """One transaction with RLS context bound via transaction-local settings (SET LOCAL semantics).

    Callers MUST pass tenant_id only after validating membership server-side.
    """
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.user_id', :u, true), set_config('app.tenant_id', :t, true)"),
            {"u": str(user_id) if user_id else "", "t": str(tenant_id) if tenant_id else ""},
        )
        yield conn
