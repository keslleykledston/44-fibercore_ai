"""Runs LAST: it recreates the schema, wiping the shared seed."""
from sqlalchemy import text


def test_migration_hardens_preexisting_role(migrated, admin_url):
    """Re-running role setup must strip dangerous attributes from a pre-existing fibercore_app."""
    import os
    import subprocess
    import sys

    from tests.conftest import API_DIR, APP_PW, RBAC_PW, WORKER_PW
    with migrated.begin() as c:
        c.execute(text("ALTER ROLE fibercore_app BYPASSRLS"))
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW, "WORKER_DB_PASSWORD": WORKER_PW, "RBAC_DB_PASSWORD": RBAC_PW}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=True)
    with migrated.connect() as c:
        row = c.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='fibercore_app'")).one()
        assert (row.rolsuper, row.rolbypassrls) == (False, False)


def test_0004_downgrade_removes_edge_agent_and_restores_role_checks(migrated, admin_url):
    import os
    import subprocess
    import sys

    from tests.conftest import API_DIR, APP_PW, RBAC_PW, WORKER_PW
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW, "WORKER_DB_PASSWORD": WORKER_PW, "RBAC_DB_PASSWORD": RBAC_PW}
    with migrated.begin() as c:
        tid = c.execute(text("INSERT INTO tenants(name) VALUES ('dg') RETURNING id")).scalar()
        eid = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'e') RETURNING id"), {"t": tid}).scalar()
        c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,'a','edge_agent','x',:e)"), {"t": tid, "e": eid})
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0003"], cwd=API_DIR, env=env, check=True)
    with migrated.connect() as c:
        assert c.execute(text("SELECT count(*) FROM service_accounts WHERE role='edge_agent'")).scalar() == 0
    import pytest
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError), migrated.begin() as c:  # separate transaction: CHECK must reject edge_agent
        c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash) VALUES (:t,'n','edge_agent','x')"), {"t": tid})
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env, check=True)


def test_0013_refuses_colliding_identity_data_instead_of_merging_it(migrated, admin_url):
    import os
    import subprocess
    import sys

    from tests.conftest import API_DIR, APP_PW, RBAC_PW, WORKER_PW
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW, "WORKER_DB_PASSWORD": WORKER_PW, "RBAC_DB_PASSWORD": RBAC_PW}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=API_DIR, env=env, capture_output=True, text=True)  # noqa: E731, S603
    assert run("downgrade", "0012").returncode == 0
    with migrated.begin() as c:
        tid = c.execute(text("INSERT INTO tenants(name) VALUES ('m13') RETURNING id")).scalar()
        eid = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'e13') RETURNING id"), {"t": tid}).scalar()
        for s in ("collide-1", "COLLIDE-1"):  # allowed by the old schema: two rows that only differ by case
            c.execute(text("INSERT INTO cpes(tenant_id, edge_id, canonical_serial) VALUES (:t,:e,:s)"), {"t": tid, "e": eid, "s": s})
    r = run("upgrade", "head")
    assert r.returncode != 0 and "0013 refused" in r.stderr + r.stdout, r.stderr[-600:]
    assert "collide-1" not in (r.stderr + r.stdout).lower()  # the message carries counts, never identifiers
    with migrated.begin() as c:
        c.execute(text("DELETE FROM cpes WHERE tenant_id = :t"), {"t": tid})
        c.execute(text("INSERT INTO cpes(tenant_id, edge_id, canonical_serial) VALUES (:t,:e,'lower-fixme')"), {"t": tid, "e": eid})
    assert run("upgrade", "head").returncode == 0  # clean data: canonicalised, constraints in place
    with migrated.connect() as c:
        assert c.execute(text("SELECT canonical_serial FROM cpes WHERE tenant_id = :t"), {"t": tid}).scalar() == "LOWER-FIXME"


def test_0052_downgrade_removes_the_acs_registry_completely_and_upgrade_brings_it_back(migrated, admin_url):
    """ADR-0046 D2: the CPEs survive (only their `acs_id` goes), the table, its function, the trigger and the constraints leave no trace, and the way back up is clean."""
    import os
    import subprocess
    import sys

    from tests.conftest import API_DIR, APP_PW, RBAC_PW, WORKER_PW
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW, "WORKER_DB_PASSWORD": WORKER_PW, "RBAC_DB_PASSWORD": RBAC_PW}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=API_DIR, env=env, capture_output=True, text=True)  # noqa: E731, S603
    with migrated.begin() as c:
        tid = c.execute(text("INSERT INTO tenants(name) VALUES ('m52') RETURNING id")).scalar()
        eid = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'e52') RETURNING id"), {"t": tid}).scalar()
        aid = c.execute(text("INSERT INTO acs_connections(tenant_id, name, kind, edge_id) VALUES (:t,'Genie','genieacs',:e) RETURNING id"), {"t": tid, "e": eid}).scalar()
        c.execute(text("INSERT INTO cpes(tenant_id, edge_id, canonical_serial, acs_id) VALUES (:t,:e,'M52-0001',:a)"), {"t": tid, "e": eid, "a": aid})
    r = run("downgrade", "0051")
    assert r.returncode == 0, r.stderr[-800:]
    with migrated.connect() as c:
        assert c.execute(text("SELECT to_regclass('public.acs_connections')")).scalar() is None
        assert c.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'cpes' AND column_name = 'acs_id'")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM pg_proc WHERE proname IN ('app_acs_edge_report', 'acs_connections_guard')")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM cpes WHERE canonical_serial = 'M52-0001'")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM pg_constraint WHERE conname = 'cpes_acs_fk'")).scalar() == 0
    r = run("upgrade", "head")
    assert r.returncode == 0, r.stderr[-800:]
    with migrated.connect() as c:
        assert c.execute(text("SELECT to_regclass('public.acs_connections')")).scalar() is not None
        assert c.execute(text("SELECT acs_id FROM cpes WHERE canonical_serial = 'M52-0001'")).scalar() is None   # the link was local to the registry and is gone; nothing is invented on the way up
        assert c.execute(text("SELECT count(*) FROM pg_proc WHERE proname = 'app_acs_edge_report'")).scalar() == 1
