"""Isolamento entre duas ORGANIZAÇÕES (ADR-0046 D1): prova, com principals de cada uma, que nada de uma aparece nem é alterável pela outra.

Método (a evidência está em docs/operations/ISOLAMENTO_ORGANIZACOES.md):
* as duas organizações NASCEM pelo caminho real da tela (conta operadora + MFA recente, função de plataforma, convite do primeiro administrador aceito);
* cada uma recebe um Edge com conta de serviço, OLT lida pelo Edge (com ONUs), OLT cadastrada na tela (com POP), CPE, chave de selagem confirmada, entregas de segredo e de conexão, convite pendente,
  um segundo membro, flags próprias e auditoria;
* **impressões digitais**: todo UUID e todo rótulo (nome, serial, e-mail, todos com uma marca única da organização) de CADA organização, lidos como dono direto do banco; uma resposta à outra
  organização NUNCA pode conter nenhum deles;
* **varredura de rotas**: todas as rotas GET sem parâmetro do inventário RBAC, com o administrador e o Edge de cada lado; todas as rotas GET com identificador, com o identificador da OUTRA organização,
  que devem responder IGUAL (status e corpo) a um identificador que não existe (404 idêntico);
* **escritas**: cada escrita sobre um objeto da outra organização responde igual a um objeto inexistente e o estado inteiro da outra (todas as tabelas com `tenant_id`) permanece idêntico (resumo MD5);
* **tenant_id do corpo, do cabeçalho e da consulta** é ignorado ou recusado, nunca obedecido; token de Edge de uma não escreve na outra; token com `tid` trocado é recusado;
* **banco**: com a role da aplicação, em TODA tabela com `tenant_id` (RLS ligada e forçada), nada de outra organização é visível, alterável ou apagável."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core import olt_secrets
from app.core.db import make_engine, scoped_connection
from app.core.rbac_matrix import inventory
from app.core.security import ROLE_PERMISSIONS, hash_secret, issue_token
from app.core.settings import get_settings
from tests import olt_secret_helpers as H
from tests.org_helpers import PW, _h, _post, _with_mfa_session

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ADMIN_PW = "isolamento-seguro-ok-77"
SECRET_AGENT = "iso-agent-secret-0123456789"
HOST_KEY = "SHA256:" + "A" * 43
COVERAGE: dict[str, int] = {}


@dataclass
class Org:
    tag: str                              # unique mark inside every name, serial and e-mail of this organization
    tid: UUID
    name: str
    admin_email: str
    admin_id: UUID = None                 # type: ignore[assignment]
    admin: dict = field(default_factory=dict)    # headers of the administrator (own workspace)
    edge: UUID = None                     # type: ignore[assignment]
    sa: UUID = None                       # type: ignore[assignment]
    agent: dict = field(default_factory=dict)
    pop: str = ""
    snap_olt: str = ""
    snap_olt_name: str = ""
    fleet_olt: str = ""
    onus: list = field(default_factory=list)
    cpe: str = ""
    invite: str = ""
    invite_token: str = ""
    member2: str = ""
    deliveries: dict = field(default_factory=dict)
    key_id: str = ""
    priv: object = None
    point: bytes = b""
    ids: set = field(default_factory=set)
    flags: dict = field(default_factory=dict)


def _tenant_tables(migrated) -> list[str]:
    with migrated.connect() as c:
        return [r[0] for r in c.execute(text(
            "SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' AND t.table_type = 'BASE TABLE' ORDER BY 1"))]


def _digest(migrated, tid) -> dict[str, tuple[int, str]]:
    """Every row of every tenant table of one organization, as one fingerprint per table: nothing may change when the OTHER organization acts on it."""
    out = {}
    with migrated.connect() as c:
        for t in _tenant_tables(migrated):
            out[t] = tuple(c.execute(text(f"SELECT count(*), md5(COALESCE(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x WHERE tenant_id = :t"), {"t": tid}).one())  # noqa: S608
    return out


def _fingerprints(migrated, tid) -> set[str]:
    ids = set()
    with migrated.connect() as c:
        for t in _tenant_tables(migrated):
            for (row,) in c.execute(text(f"SELECT to_json(x)::text FROM {t} x WHERE tenant_id = :t"), {"t": tid}):  # noqa: S608
                ids |= set(UUID_RE.findall(row))
    return ids


@pytest.fixture(scope="module")
def mclient(seed):
    from app.main import app
    with TestClient(app) as c:
        yield c


def _agent_headers(client, sa, secret=SECRET_AGENT):
    r = client.post("/v1/auth/service-token", json={"client_id": str(sa), "client_secret": secret})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seal_delivery(org: Org, olt_name: str, kind: str):
    did = str(uuid4())
    exp = int(time.time()) + 1800
    aad = olt_secrets.aad(tenant_id=org.tid, edge_id=org.edge, olt_name=olt_name, kind=kind, delivery_id=did, key_id_=org.key_id, expires_at_unix=exp)
    plain = {"kind": kind, "username": "u", "password": "p"} if kind == "ssh_login" else {"kind": kind, "action": "set", "address": "10.77.0.5", "port": 22}
    blob = H.seal(org.point, json.dumps(plain, separators=(",", ":")).encode(), aad, org.key_id)
    return {"delivery_id": did, "kind": kind, "key_id": org.key_id, "expires_at": exp, "sealed": olt_secrets.b64url_encode(blob)}


def _build_org(client, migrated, operator_token, idx: int) -> Org:
    tag = f"iso{'ab'[idx]}{uuid4().hex[:6]}"
    r, body = _post(client, operator_token, name=f"Org {tag}", admin_email=f"adm.{tag}@example.com", admin_name=f"Admin {tag}")
    assert r.status_code == 201, r.text
    out = r.json()
    org = Org(tag=tag, tid=UUID(out["tenant_id"]), name=out["name"], admin_email=body["admin_email"])
    ok = client.post(f"/v1/invites/{out['invite']['token']}/accept", json={"name": f"Admin {tag}", "password": ADMIN_PW})
    assert ok.status_code == 200, ok.text
    tok = client.post("/v1/auth/token", json={"email": org.admin_email, "password": ADMIN_PW}).json()["access_token"]
    org.admin = {**_h(tok), "X-Workspace-ID": str(org.tid)}
    with migrated.begin() as c:
        org.admin_id = c.execute(text("SELECT id FROM users_global WHERE email = :e"), {"e": org.admin_email}).scalar()
        org.edge = c.execute(text("INSERT INTO edges(tenant_id, name) VALUES (:t, :n) RETURNING id"), {"t": org.tid, "n": f"edge-{tag}"}).scalar()
        org.sa = c.execute(text("INSERT INTO service_accounts(tenant_id, name, role, secret_hash, edge_id) VALUES (:t,:n,'edge_agent',:h,:e) RETURNING id"),
                           {"t": org.tid, "n": f"agent-{tag}", "h": hash_secret(SECRET_AGENT), "e": org.edge}).scalar()
        # a second member (an engineer) and per-organization feature overrides that differ between the two
        u = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:n,:h) RETURNING id"), {"e": f"eng.{tag}@example.com", "n": f"Eng {tag}", "h": hash_secret(PW)}).scalar()
        c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,'engineer')"), {"t": org.tid, "u": u})
        org.member2 = str(u)
        org.flags = {"fleet_manager": True, "fleet_secrets": True, "fleet_provision": True, "onu_discovery": idx == 0, "profile_studio": idx == 1}
        for f, v in org.flags.items():
            c.execute(text("INSERT INTO tenant_features(tenant_id, feature, enabled) VALUES (:t,:f,:v)"), {"t": org.tid, "f": f, "v": v})
    org.agent = _agent_headers(client, org.sa)
    # inventory the Edge read (an OLT with two ONUs), a CPE, a POP and an OLT registered on the screen
    org.snap_olt_name = f"OLT-{tag}"
    obs = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    snap = {"edge_id": str(org.edge), "observed_at": obs, "name": org.snap_olt_name, "vendor": "huawei", "model": "MA5800-X7", "firmware": "R018", "driver_level": "observed",
            "pons": [{"pon_path": "0/1/0", "status": "up"}],
            "onus": [{"serial": f"HWTC{idx}{i:03d}", "pon_path": "0/1/0", "status": "online", "rx_dbm": -21.5} for i in (1, 2)]}
    assert client.post("/v1/edge/olt-snapshots", headers=org.agent, json=snap).status_code == 202
    cpe = {"edge_id": str(org.edge), "observed_at": obs, "cpes": [{"canonical_serial": f"CPE{tag}".upper(), "vendor": "Huawei", "model": "HG8245H",
           "binding": {"protocol": "tr069", "external_id": f"ext-{tag}", "connector_id": f"genieacs-{tag}"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=org.agent, json=cpe).status_code == 202
    pop = client.post("/v1/pops", headers=org.admin, json={"name": f"POP {tag}"})
    assert pop.status_code == 201, pop.text
    org.pop = pop.json()["id"]
    reg = client.post("/v1/fleet/olts", headers=org.admin, json={"name": f"REG-{tag}", "edge_id": str(org.edge), "vendor": "huawei", "pop_id": org.pop, "mgmt_address": f"10.7{idx}.0.9",
                                                                  "snmp_version": "v2c", "mgmt_protocol": "ssh", "mgmt_port": 22, "mgmt_transport": "cli", "host_key_sha256": HOST_KEY})
    assert reg.status_code == 201, reg.text
    org.fleet_olt = reg.json()["id"]
    # the Edge publishes its seal key, a person confirms it, then a credential and a connection are handed over
    org.priv, pub = H.new_edge_key()
    org.point = olt_secrets.b64url_decode(pub)
    org.key_id = olt_secrets.key_id(org.point)
    assert client.post("/v1/edge/seal-key", headers=org.agent, json={"public_key": pub}).status_code == 200
    conf = client.post(f"/v1/fleet/edges/{org.edge}/seal-key/confirm", headers=org.admin, json={"key_id": org.key_id, "fingerprint": olt_secrets.fingerprint(org.point)})
    assert conf.status_code == 200, conf.text
    for kind in ("ssh_login", "olt_connection"):
        d = _seal_delivery(org, f"REG-{tag}", kind)
        r = client.post(f"/v1/fleet/olts/{org.fleet_olt}/secret-deliveries", headers=org.admin, json=d)
        assert r.status_code == 202, r.text
        org.deliveries[kind] = d["delivery_id"]
    inv = client.post("/v1/team/invites", headers=org.admin, json={"email": f"conv.{tag}@example.com", "name": f"Conv {tag}", "role": "noc_n1"})
    assert inv.status_code == 201, inv.text
    org.invite, org.invite_token = inv.json()["id"], inv.json()["token"]
    # ids as the API returns them
    org.onus = [o["id"] for o in client.get("/v1/onus", headers=org.admin).json()["items"]] if isinstance(client.get("/v1/onus", headers=org.admin).json(), dict) else [o["id"] for o in client.get("/v1/onus", headers=org.admin).json()]
    with migrated.connect() as c:
        org.snap_olt = str(c.execute(text("SELECT id FROM olts WHERE tenant_id = :t AND name = :n"), {"t": org.tid, "n": org.snap_olt_name}).scalar())
        org.cpe = str(c.execute(text("SELECT id FROM cpes WHERE tenant_id = :t"), {"t": org.tid}).scalar())
    # some audit of its own
    assert client.get("/v1/tenant", headers=org.admin).status_code == 200
    assert org.snap_olt and org.cpe and len(org.onus) == 2
    return org


@pytest.fixture(scope="module")
def world(mclient, migrated, seed):
    with migrated.begin() as c:
        c.execute(text("UPDATE audit_log SET created_at = created_at - interval '3 hours' WHERE action = 'platform.organization.created' AND created_at > now() - interval '2 hours'"))
        c.execute(text("DELETE FROM login_attempts"))
        email = f"op{uuid4().hex[:8]}@example.com"
        uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash, is_platform_operator) VALUES (:e,'Operadora Iso',:h,true) RETURNING id"), {"e": email, "h": hash_secret(PW)}).scalar()
    who = {"email": email, "id": uid}
    token = _with_mfa_session(mclient, who)["access_token"]
    a = _build_org(mclient, migrated, token, 0)
    b = _build_org(mclient, migrated, token, 1)
    fa, fb = _fingerprints(migrated, a.tid), _fingerprints(migrated, b.tid)
    shared = fa & fb                     # e.g. the platform operator who made both: not an identifier of ONE of them
    a.ids, b.ids = fa - shared - {str(a.tid)} | {str(a.tid)}, fb - shared - {str(b.tid)} | {str(b.tid)}
    assert len(a.ids) > 20 and len(b.ids) > 20 and not (a.ids & b.ids)
    return {"A": a, "B": b, "migrated": migrated, "client": mclient, "operator": who, "op_token": token}


def _pairs():
    return [("A", "B"), ("B", "A")]


def _leaks(text_: str, other: Org) -> list[str]:
    low = text_.lower()
    found = [i for i in other.ids if i in low]
    if other.tag in low:
        found.append(other.tag)
    return found


def _norm(resp, ident: str) -> tuple[int, str]:
    return resp.status_code, resp.text.replace(ident, "<ID>")


# ================================================================== both were born through the screen path
def test_the_two_organizations_were_created_by_the_platform_function_and_are_independent(world):
    a, b, m = world["A"], world["B"], world["migrated"]
    with m.connect() as c:
        for o in (a, b):
            acts = {r[0] for r in c.execute(text("SELECT action FROM audit_log WHERE tenant_id = :t AND action LIKE 'platform.organization.%'"), {"t": o.tid})}
            assert acts == {"platform.organization.created", "platform.organization.requested"}
            roles = c.execute(text("SELECT role FROM tenant_memberships WHERE tenant_id = :t AND user_id = :u"), {"t": o.tid, "u": o.admin_id}).scalar()
            assert roles == "isp_admin"
            assert not c.execute(text("SELECT 1 FROM tenant_memberships WHERE tenant_id = :t AND user_id = :u"), {"t": o.tid, "u": world["operator"]["id"]}).first()
    assert a.tid != b.tid and not (a.ids & b.ids)
    COVERAGE["fingerprints_per_org"] = min(len(a.ids), len(b.ids))


# ================================================================== lists: nothing of the other, counts are the organization's own
@pytest.mark.parametrize("me,other", _pairs())
def test_every_parameterless_get_route_never_shows_the_other_organization(world, me, other):
    mine, theirs, client = world[me], world[other], world["client"]
    admin_perms = ROLE_PERMISSIONS["isp_admin"]
    agent_perms = ROLE_PERMISSIONS["edge_agent"]
    swept = 0
    for r in inventory():
        if r["method"] != "GET" or "{" in r["path"] or r["path"] in ("/metrics", "/livez", "/readyz", "/version", "/v1/platform/organizations"):
            continue
        perms = set(r["permissions"])
        principals = []
        if not perms or perms & admin_perms:
            principals.append(mine.admin)
        if perms and perms & agent_perms:
            principals.append(mine.agent)
        for hdrs in principals:
            resp = client.get(r["path"], headers=hdrs)
            assert resp.status_code < 500, (r["path"], resp.status_code, resp.text[:200])
            leaks = _leaks(resp.text, theirs)
            assert not leaks, f"{r['path']} as {me} leaked {other}: {leaks[:3]}"
            swept += 1
    assert swept >= 30, swept
    COVERAGE["get_routes_swept_per_direction"] = swept


@pytest.mark.parametrize("me,other", _pairs())
def test_counts_and_lists_are_the_organizations_own(world, me, other):
    mine, theirs, client, m = world[me], world[other], world["client"], world["migrated"]
    with m.connect() as c:
        def n(sql):
            return c.execute(text(sql), {"t": mine.tid}).scalar()
        expect_olts = n("SELECT count(*) FROM olts WHERE tenant_id = :t")
        expect_onus = n("SELECT count(*) FROM onus WHERE tenant_id = :t")
        expect_cpes = n("SELECT count(*) FROM cpes WHERE tenant_id = :t")
        expect_pops = n("SELECT count(*) FROM pops WHERE tenant_id = :t")
        expect_edges = n("SELECT count(*) FROM edges WHERE tenant_id = :t")
        expect_members = n("SELECT count(*) FROM tenant_memberships WHERE tenant_id = :t")
    olts = client.get("/v1/olts", headers=mine.admin).json()
    assert {o["id"] for o in olts} == {mine.snap_olt, mine.fleet_olt} and len(olts) == expect_olts
    fleet = client.get("/v1/fleet/olts", headers=mine.admin).json()
    assert {o["id"] for o in fleet["items"]} == {mine.snap_olt, mine.fleet_olt}
    onus = client.get("/v1/onus", headers=mine.admin).json()
    onus = onus["items"] if isinstance(onus, dict) else onus
    assert len(onus) == expect_onus == 2 and {o["id"] for o in onus} == set(mine.onus)
    assert len(client.get("/v1/cpes", headers=mine.admin).json()) == expect_cpes == 1
    pops = client.get("/v1/pops", headers=mine.admin).json()
    assert [p["id"] for p in pops["items"]] == [mine.pop] and len(pops["items"]) == expect_pops
    assert [e["id"] for e in client.get("/v1/edges", headers=mine.admin).json()] == [str(mine.edge)] and expect_edges == 1
    team = client.get("/v1/team", headers=mine.admin).json()
    assert len(team["members"]) == expect_members == 2
    assert {m_["email"] for m_ in team["members"]} == {mine.admin_email, f"eng.{mine.tag}@example.com"}
    assert [i["id"] for i in team["invites"]] == [mine.invite]
    assert client.get("/v1/tenant", headers=mine.admin).json()["id"] == str(mine.tid)
    feats = {f["feature"]: f for f in client.get("/v1/tenant/features", headers=mine.admin).json()}
    for f, v in mine.flags.items():
        assert feats[f]["enabled"] is v and feats[f]["source"] == "tenant"
    assert feats["onu_discovery"]["enabled"] != world[other].flags["onu_discovery"] or me == other      # the two have different overrides, each sees its own
    audit = client.get("/v1/audit?limit=200", headers=mine.admin).json()
    assert audit and all(not _leaks(json.dumps(a_), theirs) for a_ in audit)
    assert {a_["target_id"] for a_ in audit if a_["action"] == "tenant.read"} == {str(mine.tid)}
    deliveries = client.get(f"/v1/fleet/olts/{mine.fleet_olt}/secret-deliveries", headers=mine.admin).json()
    assert {d["id"] for d in deliveries["items"]} == set(mine.deliveries.values())
    assert not _leaks(json.dumps(deliveries), theirs) and "sealed" not in json.dumps(deliveries)
    COVERAGE["lists_checked"] = 12


# ================================================================== details by id: the other organization's id answers like an id that does not exist
def _kind_ids(org: Org) -> dict[str, list[str]]:
    return {"olt_id": [org.snap_olt, org.fleet_olt], "onu_id": org.onus, "cpe_id": [org.cpe], "edge_id": [str(org.edge)], "pop_id": [org.pop],
            "delivery_id": list(org.deliveries.values()), "user_id": [org.member2, str(org.admin_id)], "invite_id": [org.invite]}


@pytest.mark.parametrize("me,other", _pairs())
def test_get_by_id_of_the_other_organization_is_the_same_404_as_an_unknown_id(world, me, other):
    mine, theirs, client = world[me], world[other], world["client"]
    kinds = _kind_ids(theirs)
    probed = skipped = 0
    for r in inventory():
        if r["method"] != "GET" or "{" not in r["path"]:
            continue
        params = re.findall(r"\{(\w+)\}", r["path"])
        perms = set(r["permissions"])
        hdrs = mine.admin if (not perms or perms & ROLE_PERMISSIONS["isp_admin"]) else mine.agent
        if len(params) != 1 or params[0] not in kinds:
            skipped += 1
            continue
        for value in kinds[params[0]]:
            theirs_resp = client.get(r["path"].replace("{" + params[0] + "}", value), headers=hdrs)
            nothing = str(uuid4())
            ghost_resp = client.get(r["path"].replace("{" + params[0] + "}", nothing), headers=hdrs)
            assert _norm(theirs_resp, value) == _norm(ghost_resp, nothing), (r["path"], theirs_resp.status_code, ghost_resp.status_code, theirs_resp.text[:150], ghost_resp.text[:150])
            assert not _leaks(theirs_resp.text, theirs), r["path"]
            probed += 1
    assert probed >= 20, probed
    COVERAGE["get_by_id_probes_per_direction"] = probed
    COVERAGE["get_by_id_routes_without_an_object_in_this_world"] = skipped


@pytest.mark.parametrize("me,other", _pairs())
def test_the_other_organizations_workspace_header_is_the_same_404_as_an_unknown_workspace(world, me, other):
    mine, theirs, client = world[me], world[other], world["client"]
    for path in ("/v1/olts", "/v1/onus", "/v1/tenant", "/v1/team", "/v1/audit", "/v1/pops", "/v1/fleet/olts"):
        a_ = client.get(path, headers={**mine.admin, "X-Workspace-ID": str(theirs.tid)})
        b_ = client.get(path, headers={**mine.admin, "X-Workspace-ID": str(uuid4())})
        assert _norm(a_, str(theirs.tid)) == (b_.status_code, b_.text) and a_.status_code == 404, path
    for path, body in (("/v1/team/invites", {"email": "x@example.com", "role": "noc_n1"}), ("/v1/pops", {"name": "Invasao"})):
        assert client.post(path, headers={**mine.admin, "X-Workspace-ID": str(theirs.tid)}, json=body).status_code == 404


# ================================================================== writes against the other organization change NOTHING there and answer like a missing object
def _attacks(theirs: Org):
    sealed = _seal_delivery(theirs, f"REG-{theirs.tag}", "ssh_login")
    return [
        ("PATCH", f"/v1/pops/{theirs.pop}", {"name": "Pop Sequestrada"}, theirs.pop),
        ("PATCH", f"/v1/fleet/olts/{theirs.fleet_olt}", {"label": "sequestrada"}, theirs.fleet_olt),
        ("PATCH", f"/v1/fleet/olts/{theirs.fleet_olt}", {"mgmt_address": "10.99.99.99", "mgmt_protocol": "ssh", "host_key_sha256": HOST_KEY}, theirs.fleet_olt),
        ("POST", f"/v1/fleet/olts/{theirs.fleet_olt}/connection-test", None, theirs.fleet_olt),
        ("GET", f"/v1/fleet/olts/{theirs.fleet_olt}/connection-tests", None, theirs.fleet_olt),
        ("POST", f"/v1/fleet/olts/{theirs.fleet_olt}/secret-deliveries", sealed, theirs.fleet_olt),
        ("POST", f"/v1/fleet/olts/{theirs.snap_olt}/secret-deliveries", sealed, theirs.snap_olt),
        ("POST", f"/v1/fleet/edges/{theirs.edge}/seal-key/confirm", {"key_id": theirs.key_id, "fingerprint": olt_secrets.fingerprint(theirs.point)}, str(theirs.edge)),
        ("DELETE", f"/v1/team/invites/{theirs.invite}", None, theirs.invite),
        ("POST", f"/v1/team/invites/{theirs.invite}/renew", None, theirs.invite),
        ("POST", f"/v1/team/members/{theirs.member2}/password-reset", None, theirs.member2),
        ("POST", f"/v1/team/members/{theirs.member2}/remove", {"reason": "teste de isolamento"}, theirs.member2),
        ("POST", f"/v1/team/members/{theirs.admin_id}/remove", {"reason": "teste de isolamento"}, str(theirs.admin_id)),
        ("PUT", f"/v1/members/{theirs.member2}/role", {"role": "support", "reason": "teste de isolamento"}, theirs.member2),
        ("PUT", f"/v1/members/{theirs.admin_id}/role", {"role": "support", "reason": "teste de isolamento"}, str(theirs.admin_id)),
        ("POST", f"/v1/olts/{theirs.snap_olt}/onus/unregistered/sync", None, theirs.snap_olt),
    ]


@pytest.mark.parametrize("me,other", _pairs())
def test_writes_against_the_other_organization_answer_like_a_missing_object_and_change_nothing(world, me, other):
    mine, theirs, client, m = world[me], world[other], world["client"], world["migrated"]
    probed = 0
    for method, path, body, ident in _attacks(theirs):
        before = _digest(m, theirs.tid)
        mine_before = _digest(m, mine.tid)
        resp = client.request(method, path, headers=mine.admin, json=body)
        ghost_path = path.replace(ident, (ghost := str(uuid4())))
        ghost_resp = client.request(method, ghost_path, headers=mine.admin, json=body)
        assert _norm(resp, ident) == _norm(ghost_resp, ghost), (method, path, resp.status_code, ghost_resp.status_code, resp.text[:160], ghost_resp.text[:160])
        assert resp.status_code in (403, 404, 405, 422), (method, path, resp.status_code)      # never a success
        assert not _leaks(resp.text, theirs), path
        after = _digest(m, theirs.tid)
        assert after == before, f"{method} {path}: {[t for t in before if before[t] != after[t]]} of {other} changed"
        changed_mine = [t for t in mine_before if mine_before[t] != _digest(m, mine.tid)[t]]
        assert set(changed_mine) <= {"audit_log"}, (method, path, changed_mine)     # at most the caller's own audit of a refusal
        probed += 1
    COVERAGE["write_attempts_per_direction"] = probed


@pytest.mark.parametrize("me,other", _pairs())
def test_tenant_id_in_body_header_or_query_is_ignored_or_refused(world, me, other):
    mine, theirs, client, m = world[me], world[other], world["client"], world["migrated"]
    before = _digest(m, theirs.tid)
    base = client.get("/v1/olts", headers=mine.admin)
    for extra in ({"X-Tenant-Id": str(theirs.tid)}, {"X-Tenant": str(theirs.tid)}, {"X-Org-Id": str(theirs.tid)}, {"Tenant-Id": str(theirs.tid)}):
        r = client.get(f"/v1/olts?tenant_id={theirs.tid}&org={theirs.tid}", headers={**mine.admin, **extra})
        assert r.status_code == 200 and r.json() == base.json()
    for body in ({"name": f"Via Corpo {uuid4().hex[:5]}", "tenant_id": str(theirs.tid)}, {"name": f"Via Corpo {uuid4().hex[:5]}", "org_id": str(theirs.tid)}):
        r = client.post("/v1/pops", headers=mine.admin, json=body)
        assert r.status_code == 422, r.text            # unknown fields are refused, never obeyed
        assert str(theirs.tid) not in r.text
    ok = client.post(f"/v1/pops?tenant_id={theirs.tid}", headers={**mine.admin, "X-Tenant-Id": str(theirs.tid)}, json={"name": f"Pop Minha {uuid4().hex[:5]}"})
    assert ok.status_code == 201
    with m.connect() as c:
        assert c.execute(text("SELECT tenant_id FROM pops WHERE id = :i"), {"i": ok.json()["id"]}).scalar() == mine.tid     # it went to the caller's own organization
    assert _digest(m, theirs.tid) == before
    # the edge ingest bodies carry ids too: a tenant_id of the other organization is refused (403), nothing changes there
    hb = client.post("/v1/edge/heartbeat", headers=mine.agent, json={"edge_id": str(theirs.edge), "tenant_id": str(theirs.tid), "version": "9.9", "sent_at": "2026-11-12T10:00:00+00:00"})
    assert hb.status_code == 403
    hb2 = client.post("/v1/edge/heartbeat", headers=mine.agent, json={"edge_id": str(mine.edge), "tenant_id": str(theirs.tid), "version": "9.9", "sent_at": "2026-11-12T10:00:00+00:00"})
    assert hb2.status_code == 403
    assert _digest(m, theirs.tid) == before


# ================================================================== an Edge token of one organization writes nothing in the other
@pytest.mark.parametrize("me,other", _pairs())
def test_an_edge_token_of_one_organization_cannot_write_in_the_other(world, me, other):
    mine, theirs, client, m = world[me], world[other], world["client"], world["migrated"]
    before = _digest(m, theirs.tid)
    obs = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    snap = {"edge_id": str(theirs.edge), "observed_at": obs, "name": theirs.snap_olt_name, "vendor": "huawei", "model": "X", "firmware": "1", "driver_level": "observed",
            "pons": [{"pon_path": "0/1/0", "status": "down"}], "onus": [{"serial": "HWTC9999", "pon_path": "0/1/0", "status": "los", "rx_dbm": None}]}
    assert client.post("/v1/edge/olt-snapshots", headers=mine.agent, json=snap).status_code == 403       # not bound to that Edge
    cpe = {"edge_id": str(theirs.edge), "observed_at": obs, "cpes": [{"canonical_serial": f"CPE{theirs.tag}".upper(), "vendor": "HACKED",
                                                                    "binding": {"protocol": "tr069", "external_id": f"ext-{theirs.tag}", "connector_id": "hacked"}}]}
    assert client.post("/v1/edge/cpe-snapshots", headers=mine.agent, json=cpe).status_code == 403
    assert client.post("/v1/edge/cpe-state", headers=mine.agent, json={"edge_id": str(theirs.edge), "observed_at": obs, "items": []}).status_code in (403, 422)
    for kind, did in theirs.deliveries.items():
        r = client.post(f"/v1/edge/secret-deliveries/{did}/result", headers=mine.agent, json={"lease_token": str(uuid4()), "outcome": "applied"})
        g = client.post(f"/v1/edge/secret-deliveries/{uuid4()}/result", headers=mine.agent, json={"lease_token": str(uuid4()), "outcome": "applied"})
        assert r.status_code == g.status_code == 404, (kind, r.status_code, r.text)
    # the OLT trust state of the other organization is not writable: the report is counted as ignored, like any unknown id
    st = client.post("/v1/edge/managed-olts/state", headers=mine.agent, json={"items": [{"cloud_id": theirs.fleet_olt, "state": "trusted"}, {"cloud_id": str(uuid4()), "state": "trusted"}]})
    assert st.status_code == 200 and st.json() == {"updated": 0, "ignored": 2}
    assert client.post(f"/v1/edge/jobs/{uuid4()}/result", headers=mine.agent, json={"outcome": "SUCCEEDED"}).status_code in (404, 422)
    # a header naming the other organization changes nothing for a service token: it is bound to its own tenant by the token itself
    nxt = client.get("/v1/edge/secret-deliveries/next", headers={**mine.agent, "X-Workspace-ID": str(theirs.tid), "X-Tenant-Id": str(theirs.tid)})
    assert nxt.status_code in (200, 204) and not _leaks(nxt.text, theirs)
    assert _digest(m, theirs.tid) == before, [t for t in before if before[t] != _digest(m, theirs.tid)[t]]
    # an Edge token is no user: people's routes refuse it, and a person's token is no Edge: its routes refuse it
    assert client.get("/v1/fleet/olts", headers=mine.agent).status_code == 403
    assert client.get("/v1/edge/secret-deliveries/next", headers=mine.admin).status_code == 403
    assert client.post("/v1/edge/heartbeat", headers=mine.admin, json={"edge_id": str(mine.edge), "tenant_id": str(mine.tid), "version": "1", "sent_at": "2026-11-12T10:00:00+00:00"}).status_code == 403
    COVERAGE["edge_write_attempts_per_direction"] = 11


def test_a_service_token_naming_another_tenant_or_signed_by_someone_else_is_refused(world):
    a, b, client = world["A"], world["B"], world["client"]
    s = get_settings()
    crossed = issue_token(s, sub=a.sa, kind="service", tenant_id=b.tid)         # valid signature, but A's service account does not belong to B
    assert client.get("/v1/edge/secret-deliveries/next", headers=_h(crossed)).status_code == 401
    crossed2 = issue_token(s, sub=b.sa, kind="service", tenant_id=a.tid)
    assert client.get("/v1/edge/secret-deliveries/next", headers=_h(crossed2)).status_code == 401
    import jwt
    forged = jwt.encode({"iss": s.jwt_issuer, "aud": s.jwt_audience, "sub": str(b.sa), "kind": "service", "tid": str(b.tid), "iat": time.time(), "exp": int(time.time()) + 600}, "not-the-secret-" * 4, algorithm="HS256")
    assert client.get("/v1/edge/secret-deliveries/next", headers=_h(forged)).status_code == 401
    # a user token has no tenant claim: naming a workspace the user is not in is a 404, whoever the user is
    assert client.get("/v1/tenant", headers={**a.admin, "X-Workspace-ID": str(b.tid)}).status_code == 404


def test_the_other_organizations_delivery_is_never_handed_to_this_organizations_edge(world):
    """Both organizations have a delivery for THEIR Edge; each Edge's poll returns only its own, and the other's row does not move."""
    a, b, client, m = world["A"], world["B"], world["client"], world["migrated"]
    with m.connect() as c:
        states = {r[0]: r[1] for r in c.execute(text("SELECT id::text, status FROM olt_secret_deliveries WHERE tenant_id = ANY(:t)"), {"t": [a.tid, b.tid]})}
    assert set(states) == set(a.deliveries.values()) | set(b.deliveries.values()) and set(states.values()) <= {"PENDING", "DISPATCHED"}
    before_b = _digest(m, b.tid)
    got = client.get("/v1/edge/secret-deliveries/next", headers=a.agent)
    assert got.status_code == 200 and got.json()["id"] in a.deliveries.values() and got.json()["olt_name"] == f"REG-{a.tag}"
    assert not _leaks(got.text, b)
    assert _digest(m, b.tid) == before_b
    before_a = _digest(m, a.tid)
    got_b = client.get("/v1/edge/secret-deliveries/next", headers=b.agent)
    assert got_b.status_code == 200 and got_b.json()["id"] in b.deliveries.values() and not _leaks(got_b.text, a)
    assert _digest(m, a.tid) == before_a


# ================================================================== the database itself, as the application role, in EVERY table that carries a tenant
def test_every_table_with_a_tenant_has_row_level_security_enabled_and_forced(world):
    m = world["migrated"]
    tables = _tenant_tables(m)
    with m.connect() as c:
        weak = [t for t in tables if not c.execute(text("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid = CAST(:t AS regclass)"), {"t": f"public.{t}"}).scalar()]
        policies = {t: c.execute(text("SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = :t"), {"t": t}).scalar() for t in tables}
    assert not weak, f"tables with a tenant_id and no forced RLS: {weak}"
    assert all(v >= 1 for v in policies.values()), [t for t, v in policies.items() if v < 1]
    assert len(tables) >= 40, len(tables)
    COVERAGE["tenant_tables_with_forced_rls"] = len(tables)


@pytest.mark.parametrize("me,other", _pairs())
def test_the_application_role_sees_only_its_own_rows_in_every_tenant_table(world, app_url, me, other):
    mine, theirs, m = world[me], world[other], world["migrated"]
    eng = make_engine(app_url)
    try:
        tables = _tenant_tables(m)
        checked = 0
        for t in tables:
            with m.connect() as c:
                if not c.execute(text("SELECT has_table_privilege('fibercore_app', CAST(:t AS regclass), 'SELECT')"), {"t": f"public.{t}"}).scalar():
                    continue
                theirs_n = c.execute(text(f"SELECT count(*) FROM {t} WHERE tenant_id = :t"), {"t": theirs.tid}).scalar()  # noqa: S608
            with scoped_connection(eng, user_id=mine.admin_id, tenant_id=mine.tid) as c:
                foreign = c.execute(text(f"SELECT count(*) FROM {t} WHERE tenant_id <> :t"), {"t": mine.tid}).scalar()  # noqa: S608
                asked = c.execute(text(f"SELECT count(*) FROM {t} WHERE tenant_id = :o"), {"o": theirs.tid}).scalar()  # noqa: S608
            assert foreign == 0 and asked == 0, f"{t}: {me} sees {foreign}/{asked} rows of another organization (the other has {theirs_n})"
            with scoped_connection(eng, user_id=mine.admin_id) as c:     # no tenant selected: still nothing of the other
                assert c.execute(text(f"SELECT count(*) FROM {t} WHERE tenant_id = :o"), {"o": theirs.tid}).scalar() == 0, t  # noqa: S608
            checked += 1
        assert checked >= 35, checked
        COVERAGE["tables_selected_as_the_application_role"] = checked
    finally:
        eng.dispose()


@pytest.mark.parametrize("me,other", _pairs())
def test_the_application_role_cannot_write_or_erase_the_other_organizations_rows(world, app_url, me, other):
    mine, theirs, m = world[me], world[other], world["migrated"]
    eng = make_engine(app_url)
    before = _digest(m, theirs.tid)
    try:
        for t, ins in (("audit_log", "INSERT INTO audit_log(tenant_id, actor_id, action, target_type, target_id) VALUES (:o, :u, 'x', 'x', 'x')"),
                       ("events_outbox", "INSERT INTO events_outbox(tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) VALUES (:o, 'x', gen_random_uuid(), 'x', '1', '{}')")):
            with pytest.raises(DBAPIError) as ei, scoped_connection(eng, user_id=mine.admin_id, tenant_id=mine.tid) as c:     # WITH CHECK: the row's tenant must be the session's
                c.execute(text(ins), {"o": theirs.tid, "u": mine.admin_id})
            assert ei.value.orig.sqlstate == "42501", (t, ei.value.orig.sqlstate)
        touched = 0
        for t in _tenant_tables(m):
            for verb in ("UPDATE {t} SET tenant_id = tenant_id WHERE tenant_id = :o", "DELETE FROM {t} WHERE tenant_id = :o"):
                try:
                    with scoped_connection(eng, user_id=mine.admin_id, tenant_id=mine.tid) as c:
                        rc = c.execute(text(verb.format(t=t)), {"o": theirs.tid}).rowcount
                    assert rc == 0, f"{t}: {verb.split()[0]} reached {rc} rows of the other organization"
                    touched += 1
                except ProgrammingError:
                    continue      # the application role has no such privilege on this table at all
        assert touched >= 5
        COVERAGE["write_probes_as_the_application_role"] = touched
        # tenants / features / invites: the application role cannot even create them for the other organization
        for ins in ("INSERT INTO tenant_features(tenant_id, feature, enabled) VALUES (:o, 'fleet_manager', true)",
                    "INSERT INTO member_invites(tenant_id, purpose, email, role, token_hash, created_by, expires_at) VALUES (:o,'invite','a@b.co','isp_admin',decode(repeat('ab',32),'hex'),:u, now() + interval '1 hour')"):
            with pytest.raises(ProgrammingError), scoped_connection(eng, user_id=mine.admin_id, tenant_id=mine.tid) as c:
                c.execute(text(ins), {"o": theirs.tid, "u": mine.admin_id})
        with scoped_connection(eng, user_id=mine.admin_id, tenant_id=mine.tid) as c:
            assert [r[0] for r in c.execute(text("SELECT id FROM tenants"))] == [mine.tid]            # the tenants table shows only its own row
    finally:
        eng.dispose()
    assert _digest(m, theirs.tid) == before


def test_the_other_organizations_blob_is_not_readable_by_the_application_role(world, app_url):
    a, m = world["A"], world["migrated"]
    eng = make_engine(app_url)
    try:
        with pytest.raises(ProgrammingError), scoped_connection(eng, user_id=a.admin_id, tenant_id=a.tid) as c:
            c.execute(text("SELECT sealed FROM olt_secret_deliveries"))          # not even the owner's own organization: the blob column has no SELECT grant
    finally:
        eng.dispose()
    with m.connect() as c:
        assert c.execute(text("SELECT count(*) FROM olt_secret_deliveries WHERE tenant_id = :t AND sealed IS NOT NULL"), {"t": a.tid}).scalar() == 2


def test_invites_and_members_of_one_organization_do_not_let_the_other_in(world):
    a, b, client = world["A"], world["B"], world["client"]
    # B's pending invite is a bearer link: it works for whoever HOLDS it, but it can only ever place that person in B, never in A
    pv = client.get(f"/v1/invites/{b.invite_token}").json()
    assert pv["state"] == "valid" and pv["tenant_name"] == b.name
    ok = client.post(f"/v1/invites/{b.invite_token}/accept", json={"name": "Convidada B", "password": "outra-senha-bem-longa-91"})
    assert ok.status_code == 200
    tok = client.post("/v1/auth/token", json={"email": f"conv.{b.tag}@example.com", "password": "outra-senha-bem-longa-91"}).json()["access_token"]
    ws = client.get("/v1/auth/workspaces", headers=_h(tok)).json()
    assert [w["tenant_id"] for w in ws] == [str(b.tid)]
    assert client.get("/v1/tenant", headers={**_h(tok), "X-Workspace-ID": str(a.tid)}).status_code == 404
    assert client.get("/v1/team", headers={**_h(tok), "X-Workspace-ID": str(b.tid)}).status_code == 403       # noc_n1 cannot even read the team; and the other organization stays invisible
    # a member of A is not a member of B, and the platform delegation is the ONLY cross-organization door: it needs a live, MFA'd operator and is per workspace
    assert client.get("/v1/team", headers={**a.admin, "X-Workspace-ID": str(b.tid)}).status_code == 404


def test_the_platform_list_is_the_only_cross_organization_view_and_has_labels_and_counts_only(world):
    a, b, client = world["A"], world["B"], world["client"]
    # a member of an organization, even its isp_admin, is refused the cross-organization list
    assert client.get("/v1/platform/organizations", headers=a.admin).status_code == 403
    assert client.get("/v1/platform/organizations", headers=b.admin).status_code == 403
    ls = client.get("/v1/platform/organizations", headers=_h(world["op_token"]))
    assert ls.status_code == 200
    mine = {i["id"]: i for i in ls.json()["items"]}
    for o in (a, b):
        row = mine[str(o.tid)]
        assert (row["edges"], row["olts"], row["onus"]) == (1, 2, 2)
        assert set(row) == {"id", "name", "status", "created_at", "edges", "olts", "onus", "created_by", "created_via", "invite_state", "api_trail"}
    blob = json.dumps(ls.json())
    for o in (a, b):       # no serial, e-mail, address, OLT name or id of the inside of an organization
        assert "HWTC" not in blob and f"adm.{o.tag}" not in blob and o.snap_olt not in blob and o.fleet_olt not in blob and "10.7" not in blob


def test_negative_control_the_checks_above_do_detect_a_planted_leak(world, app_url):
    """A suite that cannot fail proves nothing: plant a policy that lets the application role read EVERY organization's POPs and show that the very same checks (the list leak scan, the
    digest, the database sweep) catch it. The policy is removed in `finally`."""
    a, b, client, m = world["A"], world["B"], world["client"], world["migrated"]
    with m.begin() as c:
        c.execute(text("CREATE POLICY zz_planted_leak ON pops FOR SELECT TO fibercore_app USING (true)"))
    eng = make_engine(app_url)
    try:
        seen = client.get("/v1/pops", headers=a.admin)
        assert _leaks(seen.text, b), "the leak scan must notice B's POP inside A's list"
        with scoped_connection(eng, user_id=a.admin_id, tenant_id=a.tid) as c:
            assert c.execute(text("SELECT count(*) FROM pops WHERE tenant_id <> :t"), {"t": a.tid}).scalar() > 0, "the database sweep must notice it too"
        ghost = client.get(f"/v1/pops/{uuid4()}", headers=a.admin)
        assert ghost.status_code in (404, 405)
    finally:
        eng.dispose()
        with m.begin() as c:
            c.execute(text("DROP POLICY zz_planted_leak ON pops"))
    assert not _leaks(client.get("/v1/pops", headers=a.admin).text, b)          # and with the policy gone the same scan is clean again
    COVERAGE["negative_control"] = 1


def test_zz_an_edge_publishing_a_seal_key_changes_only_its_own_edge_and_its_own_deliveries(world):
    """Runs after the delivery tests: a NEW key cancels the waiting deliveries of ITS Edge (ADR-0045) and nothing in the other organization."""
    a, b, client, m = world["A"], world["B"], world["client"], world["migrated"]
    before_b = _digest(m, b.tid)
    assert client.post("/v1/edge/seal-key", headers=a.agent, json={"public_key": H.new_edge_key()[1]}).status_code == 200
    assert _digest(m, b.tid) == before_b
    with m.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT status FROM olt_secret_deliveries WHERE tenant_id = :t"), {"t": a.tid})} <= {"CANCELLED"}
        assert {r[0] for r in c.execute(text("SELECT status FROM olt_secret_deliveries WHERE tenant_id = :t"), {"t": b.tid})} <= {"PENDING", "DISPATCHED"}


def test_zzz_coverage_summary(world):
    print("\nISOLATION-COVERAGE " + json.dumps(COVERAGE, sort_keys=True))
    assert COVERAGE.get("write_probes_as_the_application_role", 0) >= 5
