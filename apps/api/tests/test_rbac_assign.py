"""RBAC delivery 2 (ADR-0031): who may give which system role to whom, with the guards (own role, protected targets, last admin, concurrency,
sessions, audit). The pure policy is checked against an independent oracle; the API against a real database."""
from __future__ import annotations

import itertools
import threading
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import mfa, role_policy, settings
from app.core.security import ROLE_PERMISSIONS, hash_secret

PW = "correct horse battery"
HUMAN = ["isp_admin", "access_manager", "engineer", "noc_n2", "noc_n1", "support", "auditor", "platform_support"]


# ---------- pure policy vs an independent oracle ----------
def _oracle(actor: str, target: str, new: str, is_self: bool) -> bool:
    if is_self:
        return False
    if actor == "isp_admin":
        return new in {"isp_admin", "access_manager", "engineer", "noc_n2", "noc_n1", "support", "auditor"} and new != target
    if actor == "access_manager":
        return new in {"engineer", "noc_n2", "noc_n1", "support", "auditor"} and target not in {"isp_admin", "access_manager", "platform_support", "edge_agent"} and new != target
    return False


def test_policy_matches_the_oracle_for_every_combination():
    roles = sorted(ROLE_PERMISSIONS)
    for actor, target, new, is_self in itertools.product(roles, roles, roles, (False, True)):
        assert (role_policy.check_change(actor, target, new, is_self=is_self) is None) == _oracle(actor, target, new, is_self), (actor, target, new, is_self)


def test_only_the_two_granting_roles_hold_members_manage_and_neither_has_operational_power():
    holders = {r for r, p in ROLE_PERMISSIONS.items() if "members:manage" in p}
    assert holders == {"isp_admin", "access_manager"}
    operational = {"inventory:read", "customers:read", "incidents:read", "jobs:read", "jobs:request", "jobs:approve", "diagnostics:run", "edge:read", "inventory:write"}
    assert not (operational & ROLE_PERMISSIONS["access_manager"])


# ---------- API ----------
def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def make(migrated):
    def create(tenant_id, role: str):
        email = f"r{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:e,:h) RETURNING id"), {"e": email, "h": hash_secret(PW)}).scalar()
            c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": tenant_id, "u": uid, "r": role})
        return {"email": email, "id": uid, "tenant": tenant_id}
    return create


@pytest.fixture
def new_tenant(migrated):
    def create():
        with migrated.begin() as c:
            return c.execute(text("INSERT INTO tenants(name) VALUES (:n) RETURNING id"), {"n": f"T{uuid4().hex[:6]}"}).scalar()
    return create


def _login(client, who):
    r = client.post("/v1/auth/token", json={"email": who["email"], "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _h(client, who):
    return {**_bearer(_login(client, who)["access_token"]), "X-Workspace-ID": str(who["tenant"])}


def _with_mfa(client, who):
    """Enrols a second factor and signs in with it (an access_manager cannot do anything without one)."""
    tok = _login(client, who)["access_token"]
    secret = client.post("/v1/auth/mfa/enroll", json={"password": PW}, headers=_bearer(tok)).json()["secret"]
    a = client.post("/v1/auth/mfa/activate", json={"code": mfa._hotp(secret, mfa.current_step())}, headers=_bearer(tok))
    assert a.status_code == 200, a.text
    codes = a.json()["recovery_codes"]
    ch = _login(client, who)
    r = client.post("/v1/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": codes.pop()})
    assert r.status_code == 200, r.text
    return {**_bearer(r.json()["access_token"]), "X-Workspace-ID": str(who["tenant"])}


def _put(client, h, user_id, role, reason="teste de papel"):
    return client.put(f"/v1/members/{user_id}/role", headers=h, json={"role": role, "reason": reason})


def _role(migrated, tenant, uid):
    with migrated.begin() as c:
        return c.execute(text("SELECT role FROM tenant_memberships WHERE tenant_id=:t AND user_id=:u"), {"t": tenant, "u": uid}).scalar()


def test_admin_changes_a_role_audited_and_the_members_old_sessions_end(client, migrated, new_tenant, make):
    t = new_tenant()
    adm, eng = make(t, "isp_admin"), make(t, "engineer")
    ha, he = _h(client, adm), _h(client, eng)
    assert client.get("/v1/onus", headers=he).status_code == 200            # the engineer can read inventory...
    r = _put(client, ha, eng["id"], "noc_n1", "mudou de equipe")
    assert r.status_code == 200 and r.json()["previous_role"] == "engineer" and r.json()["role"] == "noc_n1" and r.json()["revoked_sessions"] >= 0
    assert _role(migrated, t, eng["id"]) == "noc_n1"
    assert client.get("/v1/onus", headers=he).status_code == 401            # ...and the old token (old role) stops working NOW
    with migrated.begin() as c:
        a = c.execute(text("SELECT evidence_redacted, actor_id FROM audit_log WHERE tenant_id=:t AND action='member.role_change' AND target_id=:u"),
                      {"t": t, "u": str(eng["id"])}).one()
        ev = c.execute(text("SELECT count(*) FROM events_outbox WHERE tenant_id=:t AND event_type='member.role_change' AND aggregate_id=:u"), {"t": t, "u": eng["id"]}).scalar()
    assert a.evidence_redacted["from"] == "engineer" and a.evidence_redacted["to"] == "noc_n1" and a.evidence_redacted["reason"] == "mudou de equipe"
    assert a.actor_id == adm["id"] and ev == 1


def test_refusals_have_stable_codes_and_change_nothing(client, migrated, new_tenant, make):
    t = new_tenant()
    adm, other_admin, eng = make(t, "isp_admin"), make(t, "isp_admin"), make(t, "engineer")
    ha = _h(client, adm)
    assert _put(client, ha, adm["id"], "engineer").json()["detail"] == "cannot_change_own_role"
    assert _put(client, ha, eng["id"], "engineer").status_code == 409                              # unchanged
    assert _put(client, ha, eng["id"], "platform_support").json()["detail"] == "role_not_assignable"  # delegation delivery first
    assert _put(client, ha, eng["id"], "edge_agent").json()["detail"] == "role_not_assignable"
    assert _put(client, ha, eng["id"], "nao_existe").status_code == 422
    assert _put(client, ha, eng["id"], "support", reason="ab").status_code == 422
    assert _put(client, ha, uuid4(), "support").status_code == 404
    assert _role(migrated, t, eng["id"]) == "engineer" and _role(migrated, t, other_admin["id"]) == "isp_admin"
    # a member of ANOTHER workspace does not exist for this one
    t2 = new_tenant()
    foreign = make(t2, "engineer")
    assert _put(client, ha, foreign["id"], "support").status_code == 404 and _role(migrated, t2, foreign["id"]) == "engineer"


@pytest.mark.parametrize("role", ["engineer", "noc_n2", "noc_n1", "support", "auditor"])
def test_roles_without_members_manage_cannot_change_anyone(client, new_tenant, make, role):
    t = new_tenant()
    make(t, "isp_admin")
    actor, target = make(t, role), make(t, "support")
    assert _put(client, _h(client, actor), target["id"], "engineer").status_code == 403


def test_access_manager_needs_mfa_has_no_operational_power_and_stays_inside_its_limits(client, migrated, new_tenant, make):
    t = new_tenant()
    adm, gm, sup, boss = make(t, "isp_admin"), make(t, "access_manager"), make(t, "support"), make(t, "isp_admin")
    # without a second factor it can do NOTHING, whatever MFA_REQUIRED_ROLES says
    blocked = client.get("/v1/roles", headers=_h(client, gm))
    assert blocked.status_code == 403 and blocked.json()["detail"] == "mfa_enrolment_required"
    hg = _with_mfa(client, gm)
    assert client.get("/v1/roles", headers=hg).status_code == 200
    for path in ("/v1/onus", "/v1/olts", "/v1/customers", "/v1/jobs", "/v1/cpes"):
        assert client.get(path, headers=hg).status_code == 403, path
    # what it may do
    assert _put(client, hg, sup["id"], "engineer").status_code == 200
    # what it may not
    assert _put(client, hg, sup["id"], "isp_admin").json()["detail"] == "role_not_assignable"
    assert _put(client, hg, sup["id"], "access_manager").json()["detail"] == "role_not_assignable"
    assert _put(client, hg, boss["id"], "engineer").json()["detail"] == "target_role_protected"
    assert _put(client, hg, adm["id"], "engineer").json()["detail"] == "target_role_protected"
    assert _put(client, hg, gm["id"], "support").json()["detail"] == "cannot_change_own_role"
    assert _role(migrated, t, boss["id"]) == "isp_admin" and _role(migrated, t, sup["id"]) == "engineer"
    # only an isp_admin names another access_manager
    assert _put(client, _h(client, adm), sup["id"], "access_manager").status_code == 200


def test_two_admins_demoting_each_other_through_the_api_at_once_leave_exactly_one(client, migrated, new_tenant, make):
    """End to end through HTTP. The strong, deterministic proofs of the lock are the direct-function tests below (they hold a transaction open)."""
    from fastapi.testclient import TestClient

    from app.main import app

    t = new_tenant()
    a, b = make(t, "isp_admin"), make(t, "isp_admin")
    ha, hb = _h(client, a), _h(client, b)
    out: dict = {}
    gate = threading.Barrier(2)

    def go(name, h, target):
        c = TestClient(app)
        gate.wait()
        out[name] = _put(c, h, target["id"], "engineer").status_code

    ts = [threading.Thread(target=go, args=("a", ha, b)), threading.Thread(target=go, args=("b", hb, a))]
    [x.start() for x in ts]
    [x.join() for x in ts]
    with migrated.begin() as c:
        admins = c.execute(text("SELECT count(*) FROM tenant_memberships WHERE tenant_id=:t AND role='isp_admin'"), {"t": t}).scalar()
    # the loser is refused (403/409) or, since the winner ended its sessions, no longer authenticates (401): never a second success
    assert admins == 1 and sorted(out.values())[0] == 200 and sorted(out.values())[1] in (401, 403, 409), (out, admins)


def test_database_refuses_to_leave_a_workspace_without_an_active_isp_admin(migrated, new_tenant, make):
    t = new_tenant()
    only = make(t, "isp_admin")
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text("UPDATE tenant_memberships SET role='engineer' WHERE tenant_id=:t AND user_id=:u"), {"t": t, "u": only["id"]})
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text("DELETE FROM tenant_memberships WHERE tenant_id=:t AND user_id=:u"), {"t": t, "u": only["id"]})
    assert _role(migrated, t, only["id"]) == "isp_admin"
    make(t, "isp_admin")                       # with a second active administrator the first may go
    with migrated.begin() as c:
        c.execute(text("UPDATE tenant_memberships SET role='engineer' WHERE tenant_id=:t AND user_id=:u"), {"t": t, "u": only["id"]})
    # deactivating the ACCOUNT of the only active administrator is refused too (same invariant), and a second administrator makes it possible
    t4 = new_tenant()
    solo = make(t4, "isp_admin")
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text("UPDATE users_global SET is_active=false WHERE id=:u"), {"u": solo["id"]})
    second = make(t4, "isp_admin")
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_active=false WHERE id=:u"), {"u": solo["id"]})
    with pytest.raises(DBAPIError):   # now `second` is the last ACTIVE one
        with migrated.begin() as c:
            c.execute(text("UPDATE users_global SET is_active=false WHERE id=:u"), {"u": second["id"]})
    with migrated.begin() as c:       # a member who is not an administrator, and reactivation, are never blocked
        c.execute(text("UPDATE users_global SET is_active=true WHERE id=:u"), {"u": solo["id"]})
    eng = make(t4, "engineer")
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_active=false WHERE id=:u"), {"u": eng["id"]})
    # an INACTIVE second administrator does not count
    t3 = new_tenant()
    keep, ghost = make(t3, "isp_admin"), make(t3, "isp_admin")
    with migrated.begin() as c:
        c.execute(text("UPDATE users_global SET is_active=false WHERE id=:u"), {"u": ghost["id"]})
    with pytest.raises(DBAPIError):
        with migrated.begin() as c:
            c.execute(text("UPDATE tenant_memberships SET role='engineer' WHERE tenant_id=:t AND user_id=:u"), {"t": t3, "u": keep["id"]})


def test_roles_endpoint_lists_the_catalog_per_role_and_what_the_caller_may_hand_out(client, new_tenant, make):
    t = new_tenant()
    adm, gm, nocn1 = make(t, "isp_admin"), make(t, "access_manager"), make(t, "noc_n1")
    d = client.get("/v1/roles", headers=_h(client, adm)).json()["roles"]
    by = {r["role"]: r for r in d}
    assert set(by) == set(ROLE_PERMISSIONS) and by["access_manager"]["label"] == "Gestor de Acesso"
    assert {r for r, x in by.items() if x["assignable_by_me"]} == {"isp_admin", "access_manager", "engineer", "noc_n2", "noc_n1", "support", "auditor"}
    assert {p["name"] for p in by["noc_n1"]["permissions"]} == {"tenant:read", "inventory:read", "incidents:read"}
    assert all(p["risk"] in ("R0", "R1", "R2", "R3") for r in d for p in r["permissions"])
    assert client.get("/v1/roles", headers=_h(client, nocn1)).status_code == 403
    m = client.get("/v1/members", headers=_h(client, adm)).json()
    assert m["can_manage_roles"] is True
    flags = {x["user_id"]: x["can_change_role"] for x in m["members"]}
    assert flags[str(adm["id"])] is False and flags[str(nocn1["id"])] is True and flags[str(gm["id"])] is True
    assert client.get("/v1/members", headers=_h(client, nocn1)).status_code == 403   # members:read is not part of noc_n1


def test_access_manager_is_always_an_mfa_role_even_with_an_empty_policy():
    settings.get_settings.cache_clear()
    assert "access_manager" in settings.required_mfa_roles(settings.get_settings())


@pytest.fixture(scope="module")
def rbac(rbac_url):
    from app.core.db import make_engine

    return make_engine(rbac_url)


def _call(engine, actor, tenant, target, new, reason="teste direto"):
    with engine.begin() as c:
        return c.execute(text("SELECT app_change_member_role(:a, :t, :u, :r, :why)"), {"a": actor, "t": tenant, "u": target, "r": new, "why": reason}).scalar_one()


def test_only_the_dedicated_role_can_change_a_role_and_the_runtime_role_cannot_even_with_forged_session_settings(migrated, rbac, new_tenant, make):
    from app.core.db import get_engine, scoped_connection

    t = new_tenant()
    adm, gm, sup = make(t, "isp_admin"), make(t, "access_manager"), make(t, "support")
    # the runtime role: no UPDATE on the column, no EXECUTE on the function — also when it forges the session settings the old design trusted
    with pytest.raises(DBAPIError):
        with scoped_connection(get_engine(), user_id=gm["id"], tenant_id=t) as c:
            c.execute(text("UPDATE tenant_memberships SET role='isp_admin' WHERE tenant_id=:t AND user_id=:u"), {"t": t, "u": sup["id"]})
    with pytest.raises(DBAPIError):
        with scoped_connection(get_engine(), user_id=adm["id"], tenant_id=t) as c:
            c.execute(text("SELECT app_change_member_role(:a, :t, :u, 'engineer', 'forjado')"), {"a": adm["id"], "t": t, "u": sup["id"]})
    with pytest.raises(DBAPIError):
        with get_engine().begin() as c:
            c.execute(text("SELECT set_config('app.user_id', :a, true), set_config('app.tenant_id', :t, true)"), {"a": str(adm["id"]), "t": str(t)})
            c.execute(text("SELECT app_change_member_role(:a, :t, :u, 'isp_admin', 'forjado')"), {"a": adm["id"], "t": t, "u": gm["id"]})
    assert _role(migrated, t, sup["id"]) == "support" and _role(migrated, t, gm["id"]) == "access_manager"
    # the dedicated role still gets the rules re-validated in SQL: an access_manager cannot make isp_admin / access_manager, touch a protected target, or itself
    for target, new in [(sup["id"], "isp_admin"), (sup["id"], "access_manager"), (adm["id"], "engineer"), (gm["id"], "support"), (sup["id"], "platform_support"), (sup["id"], "edge_agent")]:
        with pytest.raises(DBAPIError):
            _call(rbac, gm["id"], t, target, new)
    with pytest.raises(DBAPIError):    # a non-granting role
        _call(rbac, sup["id"], t, gm["id"], "engineer")
    with pytest.raises(DBAPIError):    # a short reason
        _call(rbac, gm["id"], t, sup["id"], "engineer", reason="x")
    assert _role(migrated, t, sup["id"]) == "support" and _role(migrated, t, adm["id"]) == "isp_admin" and _role(migrated, t, gm["id"]) == "access_manager"
    assert _call(rbac, gm["id"], t, sup["id"], "engineer")["previous_role"] == "support"   # what it MAY do goes through
    assert _role(migrated, t, sup["id"]) == "engineer"
    # the dedicated role has no table privileges of its own
    with pytest.raises(DBAPIError):
        with rbac.begin() as c:
            c.execute(text("SELECT * FROM tenant_memberships"))


def test_role_changes_answer_503_when_the_dedicated_connection_is_not_configured(client, new_tenant, make, monkeypatch):
    from app.core import db

    t = new_tenant()
    adm, sup = make(t, "isp_admin"), make(t, "support")
    ha = _h(client, adm)
    monkeypatch.delenv("RBAC_DATABASE_URL", raising=False)
    settings.get_settings.cache_clear(); db.get_rbac_engine.cache_clear()
    try:
        assert _put(client, ha, sup["id"], "engineer").status_code == 503
    finally:
        monkeypatch.undo()
        settings.get_settings.cache_clear(); db.get_rbac_engine.cache_clear()


def test_the_sql_rules_are_exactly_the_python_policy(migrated):
    with migrated.begin() as c:
        grants = {(g, a) for g, a in c.execute(text("SELECT granter, assignable FROM rbac_role_grants"))}
        protected = {r for (r,) in c.execute(text("SELECT role FROM rbac_protected_roles"))}
    assert grants == {(g, a) for g, roles in role_policy.ASSIGNABLE_BY.items() for a in roles}
    assert protected == set(role_policy.PROTECTED_TARGETS)


def test_a_role_change_signs_the_member_out_of_every_workspace_of_the_account(client, migrated, new_tenant, make):
    t1, t2 = new_tenant(), new_tenant()
    adm = make(t1, "isp_admin")
    eng = make(t1, "engineer")
    with migrated.begin() as c:   # the same account is also a member of a second workspace
        c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,'support')"), {"t": t2, "u": eng["id"]})
    tok = _login(client, eng)["access_token"]
    other = {**_bearer(tok), "X-Workspace-ID": str(t2)}
    assert client.get("/v1/onus", headers=other).status_code == 200
    assert _put(client, _h(client, adm), eng["id"], "noc_n1").status_code == 200
    assert client.get("/v1/onus", headers=other).status_code == 401    # account-wide, declared in the contract


def test_direct_concurrent_calls_to_the_function_cannot_leave_a_workspace_without_an_admin(migrated, rbac, new_tenant, make):
    import time

    t = new_tenant()
    a, b = make(t, "isp_admin"), make(t, "isp_admin")
    started, release, res = threading.Event(), threading.Event(), {}

    def first():   # holds its transaction open after demoting b
        try:
            with rbac.begin() as c:
                c.execute(text("SELECT app_change_member_role(:a, :t, :u, 'engineer', 'primeiro')"), {"a": a["id"], "t": t, "u": b["id"]})
                started.set()
                release.wait(10)
            res["1"] = "ok"
        except DBAPIError:
            started.set()
            res["1"] = "refused"

    def second():   # b demotes a while a's change is not committed yet
        started.wait(10)
        try:
            _call(rbac, b["id"], t, a["id"], "engineer", "segundo")
            res["2"] = "ok"
        except DBAPIError:
            res["2"] = "refused"

    ts = [threading.Thread(target=first), threading.Thread(target=second)]
    [x.start() for x in ts]
    time.sleep(0.8)      # with the lock the second call is waiting here; without it, it already finished
    release.set()
    [x.join() for x in ts]
    with migrated.begin() as c:
        admins = c.execute(text("SELECT count(*) FROM tenant_memberships WHERE tenant_id=:t AND role='isp_admin'"), {"t": t}).scalar()
    assert admins == 1 and sorted(res.values()) == ["ok", "refused"], (res, admins)


def test_a_direct_function_call_and_an_account_deactivation_do_not_deadlock(migrated, rbac, new_tenant, make):
    import time

    t = new_tenant()
    a, b = make(t, "isp_admin"), make(t, "isp_admin")
    out: dict = {}
    got_lock = threading.Event()

    def change():   # holds the locks a while, then touches the target's account row again like any caller of the old order would
        try:
            with rbac.begin() as c:
                c.execute(text("SELECT app_change_member_role(:a, :t, :u, 'engineer', 'direto')"), {"a": a["id"], "t": t, "u": b["id"]})
                got_lock.set()
                time.sleep(0.8)
            out["change"] = "ok"
        except DBAPIError as exc:
            got_lock.set()
            out["change"] = f"error {getattr(exc.orig, 'sqlstate', '?')}"

    def deactivate():
        got_lock.wait(10)
        try:
            with migrated.begin() as c:
                c.execute(text("SET LOCAL lock_timeout = '10s'"))
                c.execute(text("UPDATE users_global SET is_active=false WHERE id=:u"), {"u": b["id"]})
            out["deactivate"] = "ok"
        except DBAPIError as exc:
            out["deactivate"] = f"error {getattr(exc.orig, 'sqlstate', '?')}"

    ts = [threading.Thread(target=change), threading.Thread(target=deactivate)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert out == {"change": "ok", "deactivate": "ok"}, out


