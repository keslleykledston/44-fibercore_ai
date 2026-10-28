import os

from sqlalchemy import create_engine

from alembic import context

config = context.config


def _dsn() -> str:
    dsn = os.environ.get("ADMIN_DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("ADMIN_DATABASE_URL (owner role) is required for migrations")
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


engine = create_engine(_dsn())
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
