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


def test_0053_downgrade_removes_the_platform_functions_closes_pending_first_admin_invites_and_restores_the_accept(migrated, admin_url):
    """ADR-0046 D1: the downgrade of the organization migration is reversible and leaves the invite mechanism exactly as 0027 defined it."""
    import importlib.util
    import os
    import subprocess
    import sys

    from tests.conftest import API_DIR, APP_PW, RBAC_PW, WORKER_PW
    spec = importlib.util.spec_from_file_location("m0053", API_DIR / "alembic" / "versions" / "0053_platform_organizations.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = {**os.environ, "ADMIN_DATABASE_URL": admin_url, "APP_DB_PASSWORD": APP_PW, "WORKER_DB_PASSWORD": WORKER_PW, "RBAC_DB_PASSWORD": RBAC_PW}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=API_DIR, env=env, capture_output=True, text=True)  # noqa: E731, S603
    assert run("upgrade", "head").returncode == 0
    with migrated.begin() as c:
        tid = c.execute(text("INSERT INTO tenants(name) VALUES ('dg53') RETURNING id")).scalar()
        uid = c.execute(text("INSERT INTO users_global(email, display_name, is_platform_operator) VALUES ('dg53@example.com','x', true) RETURNING id")).scalar()
        c.execute(text("INSERT INTO member_invites(tenant_id, purpose, email, role, token_hash, created_by, expires_at, platform_origin) "
                       "VALUES (:t,'invite','a@example.com','isp_admin',decode(repeat('cd',32),'hex'),:u, now() + interval '1 hour', true)"), {"t": tid, "u": uid})
    r = run("downgrade", mod.down_revision)
    assert r.returncode == 0, r.stderr[-800:]
    with migrated.connect() as c:
        for fn in ("platform_create_organization(uuid, text, text, text, uuid)", "platform_list_organizations(uuid)", "platform_assert_actor(uuid)"):
            assert c.execute(text("SELECT to_regprocedure(:f)"), {"f": f"public.{fn}"}).scalar() is None, fn
        assert not c.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = 'member_invites' AND column_name = 'platform_origin'")).first()
        assert not c.execute(text("SELECT 1 FROM pg_policies WHERE policyname = 'platform_scan'")).first()
        src = c.execute(text("SELECT prosrc FROM pg_proc WHERE proname = 'app_invite_accept'")).scalar()
        assert "platform_origin" not in src and "team_actor_role(i.tenant_id, i.created_by)" in src
        assert "organizations_without_api_trail" not in c.execute(text("SELECT prosrc FROM pg_proc WHERE proname = 'app_metrics_snapshot'")).scalar()
        assert c.execute(text("SELECT revoked_at IS NOT NULL FROM member_invites WHERE tenant_id = :t"), {"t": tid}).scalar()   # no pending invite is left that the old mechanism could not honour
    assert run("upgrade", "head").returncode == 0
    with migrated.connect() as c:
        assert c.execute(text("SELECT to_regprocedure('public.platform_create_organization(uuid, text, text, text, uuid)')")).scalar() is not None
        assert "platform_origin" in c.execute(text("SELECT prosrc FROM pg_proc WHERE proname = 'app_invite_accept'")).scalar()
