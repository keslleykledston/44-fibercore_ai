"""Runs LAST: it recreates the schema, wiping the shared seed."""
from sqlalchemy import text


def test_migration_hardens_preexisting_role(migrated, admin_url):
    """Re-running role setup must strip dangerous attributes from a pre-existing fibercore_app."""
    import os
    import subprocess
    import sys

    from tests.conftest import API_DIR, APP_PW
    with migrated.begin() as c:
        c.execute(text("ALTER ROLE fibercore_app BYPASSRLS"))
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=True)
    with migrated.connect() as c:
        row = c.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='fibercore_app'")).one()
        assert (row.rolsuper, row.rolbypassrls) == (False, False)
