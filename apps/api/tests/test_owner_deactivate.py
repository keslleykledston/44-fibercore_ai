"""Owner CLI `deactivate-account`: closes homologation accounts; refuses Edge agents and isp_admin users; one outbox event each."""
import re

import pytest
from sqlalchemy import text

from tests.conftest import seed as _seed  # noqa: F401  (fixture kept together with the other owner CLI tests)


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM service_accounts WHERE name LIKE 'dact-%'"))
        c.execute(text("DELETE FROM edges WHERE name = 'dact-edge-site'"))
        c.execute(text("DELETE FROM tenant_memberships WHERE user_id IN (SELECT id FROM users_global WHERE email LIKE 'dact-%@example.test')"))
        c.execute(text("DELETE FROM users_global WHERE email LIKE 'dact-%@example.test'"))


def _sa(cli, t, name, role, capsys):
    cli.main(["create-service-account", t, name, role])
    return re.search(r"client_id=([0-9a-f-]{36})", capsys.readouterr().out).group(1)


def _user(cli, t, email, role, monkeypatch):
    monkeypatch.setenv("DACT_PW", "senha-de-teste-123456")
    cli.main(["create-user", email, "Teste Desativação", "--password-env", "DACT_PW"])
    cli.main(["add-member", t, email, role])


def test_deactivates_service_accounts_and_ends_memberships_with_audit(seed, migrated, admin_url, monkeypatch, capsys):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(seed["A"])
    sid = _sa(cli, t, "dact-req", "isp_admin", capsys)
    _user(cli, t, "dact-cap@example.test", "noc_n1", monkeypatch)
    capsys.readouterr()
    cli.main(["deactivate-account", t, "--service-account", "dact-req", "--user", "dact-cap@example.test"])
    assert "deactivated 1 service account(s) and ended 1 membership(s)" in capsys.readouterr().out
    with migrated.begin() as c:
        assert c.execute(text("SELECT is_active FROM service_accounts WHERE id = :i"), {"i": sid}).scalar() is False
        assert c.execute(text("SELECT count(*) FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id WHERE u.email = 'dact-cap@example.test'")).scalar() == 0
        assert c.execute(text("SELECT is_active FROM users_global WHERE email = 'dact-cap@example.test'")).scalar() is False
        ev = c.execute(text("SELECT count(*) FROM events_outbox WHERE tenant_id = :t AND event_type = 'account.deactivated'"), {"t": t}).scalar()
        assert ev >= 2
    cli.main(["deactivate-account", t, "--service-account", "dact-req"])   # idempotent: no second event, no error
    assert "deactivated 0 service account(s)" in capsys.readouterr().out


def test_refuses_edge_agents_isp_admin_users_unknown_names_and_an_empty_request(seed, admin_url, monkeypatch, capsys):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    t = str(seed["A"])
    cli.main(["register-edge", t, "dact-edge-site", "--site", "teste"])
    edge = capsys.readouterr().out.strip().splitlines()[-1]
    cli.main(["create-service-account", t, "dact-edge", "edge_agent", "--edge-id", edge])
    _user(cli, t, "dact-admin@example.test", "isp_admin", monkeypatch)
    for args, why in ((["--service-account", "dact-edge"], "Edge agent"), (["--user", "dact-admin@example.test"], "isp_admin"),
                      (["--service-account", "dact-nao-existe"], "expected exactly one"), (["--user", "ninguem@example.test"], "not a member"), ([], "name at least one")):
        with pytest.raises(SystemExit) as e:
            cli.main(["deactivate-account", t, *args])
        assert why in str(e.value), (args, str(e.value))


def test_a_user_who_also_belongs_to_another_tenant_is_refused_and_keeps_every_membership(seed, migrated, admin_url, monkeypatch, capsys):
    from app import cli

    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)
    a, b = str(seed["A"]), str(seed["B"])
    _user(cli, a, "dact-two@example.test", "noc_n1", monkeypatch)
    cli.main(["add-member", b, "dact-two@example.test", "noc_n1"])
    with pytest.raises(SystemExit) as e:
        cli.main(["deactivate-account", a, "--user", "dact-two@example.test"])
    assert "other tenants" in str(e.value)
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id WHERE u.email = 'dact-two@example.test'")).scalar() == 2
        assert c.execute(text("SELECT is_active FROM users_global WHERE email = 'dact-two@example.test'")).scalar() is True
