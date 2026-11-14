"""Encerrar organização (ADR-0050, fatia E): o operador PEDE (carência de 7 dias, só suspensa e não demonstração); o dono exporta e depois apaga, no host, com tudo conferido; o registro fica.

Provas: pré-condições (suspensa, não demo, pedido aberto, carência, nome exato, arquivo do export com o mesmo sha256, dado igual ao exportado); exportação sem coluna de segredo e sem
sobrescrever; exclusão total (TODA tabela com tenant_id) só da organização alvo; conta que só existia ali é desativada, a compartilhada não; reativar cancela o pedido; a aplicação não lê o registro."""
from __future__ import annotations

import json
import tarfile
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app import cli
from app.core import org_close
from app.core.db import make_engine
from app.core.security import hash_secret
from tests.conftest import SECRET
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, role=None, tenant_id=None):
        email = f"c{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash, is_platform_operator) VALUES (:e,:n,:h,:o) RETURNING id"),
                            {"e": email, "n": f"Pessoa {email[:6]}", "h": hash_secret(PW), "o": operator}).scalar()
            if role:
                c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": tenant_id, "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


@pytest.fixture(autouse=True)
def _window(migrated):
    with migrated.begin() as c:
        c.execute(text("UPDATE audit_log SET created_at = created_at - interval '3 hours' WHERE action = 'platform.organization.created' AND created_at > now() - interval '2 hours'"))
    yield


@pytest.fixture
def operator(client, make):
    who = make(operator=True)
    who["token"] = _with_mfa_session(client, who)["access_token"]
    return who


def _data(migrated, tid, shared=None):
    """Rows in many tables of the organization: an Edge and its service account, an OLT with PON/ONU, a limit, a policy, features."""
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid})
        e = c.execute(text("INSERT INTO edges(tenant_id,name) VALUES (:t,'close-edge') RETURNING id"), {"t": tid}).scalar()
        c.execute(text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,'close-agent','edge_agent',:h,:e)"), {"t": tid, "h": hash_secret(SECRET), "e": e})
        o = c.execute(text("INSERT INTO olts (tenant_id, edge_id, name, vendor) VALUES (:t,:e,'OLT-CLOSE','huawei') RETURNING id"), {"t": tid, "e": e}).scalar()
        p = c.execute(text("INSERT INTO pon_ports (tenant_id, olt_id, pon_path) VALUES (:t,:o,'0/1/0') RETURNING id"), {"t": tid, "o": o}).scalar()
        c.execute(text("INSERT INTO onus (tenant_id, olt_id, pon_id, serial, status) VALUES (:t,:o,:p,'SERCLOSE01','online')"), {"t": tid, "o": o, "p": p})
        c.execute(text("INSERT INTO tenant_limits (tenant_id, max_olts) VALUES (:t, 9)"), {"t": tid})
        c.execute(text("INSERT INTO tenant_security_policy (tenant_id, mfa_required_roles) VALUES (:t, ARRAY['support'])"), {"t": tid})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'fleet_manager',true)"), {"t": tid})
        if shared:
            c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,'support')"), {"t": tid, "u": shared})


@pytest.fixture
def pair(client, operator, make, migrated):
    """TWO organizations with data (the target and a bystander), an administrator in each, one person who belongs to both, and one who belongs only to the target."""
    out = {}
    for k in ("target", "other"):
        r, body = _post(client, operator["token"])
        assert r.status_code == 201, r.text
        out[k] = {"id": r.json()["tenant_id"], "name": body["name"]}
    shared = make(role="support", tenant_id=out["target"]["id"])
    only = make(role="engineer", tenant_id=out["target"]["id"])
    for k in ("target", "other"):
        out[k]["admin"] = make(role="isp_admin", tenant_id=out[k]["id"])
    _data(migrated, out["target"]["id"], None)
    _data(migrated, out["other"]["id"], shared["id"])
    out.update(shared=shared, only=only, operator=operator)
    return out


def _h_op(pair):
    return _h(pair["operator"]["token"])


def _suspend(client, pair, which="target"):
    r = client.post(f"/v1/platform/organizations/{pair[which]['id']}/status", json={"status": "suspended", "reason": "Contrato encerrado"}, headers=_h_op(pair))
    assert r.status_code == 200, r.text


def _request(client, pair, which="target"):
    return client.post(f"/v1/platform/organizations/{pair[which]['id']}/closure", json={"reason": "Pedido do cliente"}, headers=_h_op(pair))


def _rows(migrated, tid):
    with migrated.begin() as c:
        tables = org_close.data_tables(c)
        return org_close.count_rows(c, str(tid), tables)


def _due_now(migrated, tid):
    with migrated.begin() as c:
        c.execute(text("UPDATE organization_closures SET earliest_close_at = now() - interval '1 minute' WHERE tenant_id = :t"), {"t": tid})


@pytest.fixture
def env(admin_url, monkeypatch):
    monkeypatch.setenv("ADMIN_DATABASE_URL", admin_url)


# ============================================================ the request (operator)
def test_only_a_suspended_non_demo_organization_can_be_asked_to_close_and_once(client, pair, migrated, env):
    assert _request(client, pair).status_code == 409 and _request(client, pair).json() == {"detail": "organization_not_suspended"}     # active
    _suspend(client, pair)
    r = _request(client, pair)
    assert r.status_code == 201 and r.json()["state"] == "requested"
    assert _request(client, pair).json() == {"detail": "closure_exists"}
    d = client.get(f"/v1/platform/organizations/{pair['target']['id']}", headers=_h_op(pair)).json()
    assert d["closure"]["state"] == "requested" and d["closure"]["ready"] is False and d["closure"]["export_sha256"] is None
    assert any(h["action"] == "platform.closure.requested" for h in [{"action": a[0]} for a in _audit(migrated, pair["target"]["id"])])
    with migrated.begin() as c:
        demo = c.execute(text("INSERT INTO tenants(name, demo, status) VALUES (:n, true, 'suspended') RETURNING id"), {"n": "Demo " + uuid4().hex[:8]}).scalar()
    assert client.post(f"/v1/platform/organizations/{demo}/closure", json={"reason": "Tentativa"}, headers=_h_op(pair)).json() == {"detail": "organization_is_demo"}


def _audit(migrated, tid):
    with migrated.connect() as c:
        return c.execute(text("SELECT action FROM audit_log WHERE tenant_id = :t AND action LIKE 'platform.closure.%'"), {"t": tid}).all()


def test_reactivating_or_cancelling_ends_the_request_and_only_the_operator_can_ask(client, pair, make, migrated):
    _suspend(client, pair)
    assert _request(client, pair).status_code == 201
    back = client.post(f"/v1/platform/organizations/{pair['target']['id']}/status", json={"status": "active", "reason": "Voltou atrás"}, headers=_h_op(pair))
    assert back.status_code == 200
    st = client.get(f"/v1/platform/organizations/{pair['target']['id']}", headers=_h_op(pair)).json()["closure"]
    assert st["state"] == "cancelled"
    _suspend(client, pair)
    assert _request(client, pair).status_code == 201                                     # a new request after a cancellation
    c = client.post(f"/v1/platform/organizations/{pair['target']['id']}/closure/cancel", json={"reason": "Mudou de ideia"}, headers=_h_op(pair))
    assert c.status_code == 200 and c.json()["state"] == "cancelled"
    assert client.post(f"/v1/platform/organizations/{pair['target']['id']}/closure/cancel", json={"reason": "Nada aberto"}, headers=_h_op(pair)).status_code == 404
    admin_h = _h(_login(client, pair["target"]["admin"])["access_token"])
    assert client.post(f"/v1/platform/organizations/{pair['target']['id']}/closure", json={"reason": "Eu mesmo"}, headers=admin_h).status_code == 403
    nobody = make()
    assert client.get("/v1/platform/closures", headers=_h(_login(client, nobody)["access_token"])).status_code == 403


def test_the_application_cannot_read_or_write_the_closure_record(app_engine, pair):
    for sql in ("SELECT * FROM organization_closures", "UPDATE organization_closures SET state = 'closed'", "DELETE FROM organization_closures"):
        with pytest.raises(ProgrammingError), app_engine.begin() as c:
            c.execute(text(sql))


# ============================================================ the owner's CLI
def test_the_owner_cli_refuses_until_every_condition_holds(client, pair, migrated, env, tmp_path):
    t, name = pair["target"]["id"], pair["target"]["name"]
    arch = str(tmp_path / "t.tar.gz")
    with pytest.raises(SystemExit, match="must be suspended"):
        cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch])
    _suspend(client, pair)
    with pytest.raises(SystemExit, match="no open closure request"):
        cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch])
    assert _request(client, pair).status_code == 201
    with pytest.raises(SystemExit, match="grace period ends"):
        cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch])
    _due_now(migrated, t)
    with pytest.raises(SystemExit, match="exact name"):
        cli.main(["org-close", t, "--confirm-name", name.lower() + "x", "--export-file", arch])
    with pytest.raises(SystemExit, match="run org-export first"):
        cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch])
    cli.main(["org-export", t, "--out", arch])
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        cli.main(["org-export", t, "--out", arch])
    other_file = tmp_path / "x.tar.gz"
    other_file.write_bytes(b"not the archive")
    with pytest.raises(SystemExit, match="sha256 differs"):
        cli.main(["org-close", t, "--confirm-name", name, "--export-file", str(other_file)])
    with pytest.raises(SystemExit, match="no such organization"):
        cli.main(["org-close", str(uuid4()), "--confirm-name", name, "--export-file", arch])
    with migrated.begin() as c:                                    # data changes after the export: it must be exported again
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t})
        c.execute(text("UPDATE tenant_features SET enabled = enabled"), {})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'acs_registry',false)"), {"t": t})
    with pytest.raises(SystemExit, match="data changed after the export"):
        cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch])
    with migrated.begin() as c:                                    # Codex r1 (MEDIUM): same row counts, different content must be refused too
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t})
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'acs_registry'"))
        c.execute(text("UPDATE tenant_limits SET max_olts = 10"))
    with pytest.raises(SystemExit, match="different rows\\): tenant_limits"):
        cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch])
    assert sum(_rows(migrated, t).values()) > 0                    # nothing was deleted by any refusal


def test_the_export_has_every_table_no_secret_column_and_a_manifest(client, pair, migrated, env, tmp_path):
    t = pair["target"]["id"]
    arch = tmp_path / "x.tar.gz"
    cli.main(["org-export", t, "--out", str(arch)])
    assert oct(arch.stat().st_mode & 0o777) == "0o600"
    with tarfile.open(arch) as tar:
        names = set(tar.getnames())
        man = json.load(tar.extractfile("manifest.json"))
        sa = tar.extractfile("service_accounts.jsonl").read().decode()
        olts = [json.loads(x) for x in tar.extractfile("olts.jsonl").read().decode().splitlines()]
    assert "manifest.json" in names and {"olts.jsonl", "onus.jsonl", "edges.jsonl", "tenant_limits.jsonl", "audit_log.jsonl", "tenant_memberships.jsonl"} <= names
    assert "email_queue.jsonl" not in names and "events_outbox.jsonl" not in names and "email_queue" in man["skipped_tables"]
    assert "secret_hash" not in sa and "secret_hash" not in man["tables"]["service_accounts"]["columns"] and "close-agent" in sa
    assert olts[0]["name"] == "OLT-CLOSE" and man["name"] == pair["target"]["name"] and man["tables"]["olts"]["rows"] == 1
    assert not any(c in SECRET_COLUMNS_FLAT for tbl in man["tables"].values() for c in tbl["columns"])
    with migrated.connect() as c:                                  # the export touched nothing
        assert c.execute(text("SELECT count(*) FROM tenants WHERE id = :t"), {"t": t}).scalar() == 1


SECRET_COLUMNS_FLAT = org_close.SECRET_COLUMNS


def test_closing_deletes_every_row_of_that_organization_and_only_that_one_and_keeps_the_record(client, pair, migrated, env, tmp_path, capsys):
    t, o, name = pair["target"]["id"], pair["other"]["id"], pair["target"]["name"]
    _suspend(client, pair)
    assert _request(client, pair).status_code == 201
    _due_now(migrated, t)
    arch = str(tmp_path / "t.tar.gz")
    cli.main(["org-export", t, "--out", arch])
    before_other = _rows(migrated, o)
    before_target = _rows(migrated, t)
    assert before_target["olts"] == 1 and before_target["tenant_limits"] == 1
    cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch, "--dry-run"])
    assert "dry-run" in capsys.readouterr().out and _rows(migrated, t) == before_target                        # dry-run deletes nothing
    cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch])
    assert "closed" in capsys.readouterr().out
    with migrated.begin() as c:
        assert c.execute(text("SELECT count(*) FROM tenants WHERE id = :t"), {"t": t}).scalar() == 0
        tables = org_close.data_tables(c)
        leftovers = {tb: n for tb, n in org_close.count_rows(c, t, tables).items() if n}
        assert leftovers == {}, leftovers                                                                      # EVERY table with a tenant_id, discovered, is empty for the closed organization
        assert c.execute(text("SELECT count(*) FROM tenants WHERE id = :t"), {"t": o}).scalar() == 1
    assert _rows(migrated, o) == before_other                                                                  # the bystander is untouched, table by table
    with migrated.connect() as c:
        led = c.execute(text("SELECT state, name, closed_at, closed_by, deleted_rows, export_sha256 FROM organization_closures WHERE tenant_id = :t"), {"t": t}).one()
        accounts = {r[0]: r[1] for r in c.execute(text("SELECT id, is_active FROM users_global WHERE id = ANY(:ids)"), {"ids": [pair["only"]["id"], pair["shared"]["id"], pair["target"]["admin"]["id"]]})}
    assert led.state == "closed" and led.name == name and led.closed_at is not None and led.closed_by.startswith("os:") and led.deleted_rows["olts"] == 1 and len(led.export_sha256) == 64
    assert accounts[pair["only"]["id"]] is False and accounts[pair["target"]["admin"]["id"]] is False        # belonged only there
    assert accounts[pair["shared"]["id"]] is True                                                             # still belongs to the other organization
    items = client.get("/v1/platform/closures", headers=_h_op(pair)).json()["items"]
    mine = [i for i in items if i["tenant_id"] == t]
    assert mine and mine[0]["state"] == "closed" and mine[0]["deleted_rows"]["olts"] == 1 and "@" not in json.dumps(mine[0])
    assert client.get(f"/v1/platform/organizations/{t}", headers=_h_op(pair)).status_code == 404
    lst = client.get("/v1/platform/organizations", headers=_h_op(pair)).json()
    assert all(x["id"] != t for x in lst["items"])
    # a closed organization cannot be closed again
    with pytest.raises(SystemExit, match="no such organization"):
        cli.main(["org-close", t, "--confirm-name", name, "--export-file", arch])


def test_the_table_discovery_covers_every_table_with_a_tenant_id_and_orders_children_first(migrated):
    with migrated.connect() as c:
        tables = org_close.data_tables(c)
        every = {r[0] for r in c.execute(text("SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped "
                                              "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace AND c.relname <> 'tenants'"))}
        order = org_close.delete_order(c, tables)
    assert set(tables) == every - {"organization_closures"} and len(order) == len(set(order)) == len(tables)
    assert order.index("onus") < order.index("olts") and order.index("pon_ports") < order.index("olts")      # a child goes before the table it references
    assert order.index("olts") < order.index("edges")
