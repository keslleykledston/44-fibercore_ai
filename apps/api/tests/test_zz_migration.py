"""Runs LAST: it recreates the schema, wiping the shared seed."""
from sqlalchemy import text


def test_migration_hardens_preexisting_role(migrated, admin_url):
    """Re-running role setup must strip dangerous attributes from a pre-existing fibercore_app."""
    import os
    import subprocess
    import sys

    from tests.conftest import API_DIR, APP_PW, WORKER_PW
    with migrated.begin() as c:
        c.execute(text("ALTER ROLE fibercore_app BYPASSRLS"))
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW, "WORKER_DB_PASSWORD": WORKER_PW}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=True)
    with migrated.connect() as c:
        row = c.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='fibercore_app'")).one()
        assert (row.rolsuper, row.rolbypassrls) == (False, False)


def test_0004_downgrade_removes_edge_agent_and_restores_role_checks(migrated, admin_url):
    import os
    import subprocess
    import sys

    from tests.conftest import API_DIR, APP_PW, WORKER_PW
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW, "WORKER_DB_PASSWORD": WORKER_PW}
    with migrated.begin() as c:
        tid = c.execute(text("INSERT INTO tenants(name) VALUES ('dg') RETURNING id")).scalar()
        eid = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'e') RETURNING id"), {"t": tid}).scalar()
        c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,'a','edge_agent','x',:e)"), {"t": tid, "e": eid})
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0003"], cwd=API_DIR, env=env, check=True)
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM service_accounts WHERE role='edge_agent'")).scalar() == 0
        try:
            c.execute(text("SAVEPOINT s"))
            c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash) VALUES (:t,'n','edge_agent','x')"), {"t": tid})
            raise AssertionError("edge_agent still accepted after downgrade")
        except Exception as exc:  # noqa: BLE001
            assert "AssertionError" not in type(exc).__name__
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=True)
