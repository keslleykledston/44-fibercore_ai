"""E-mail transacional (ADR-0048, fatia C): só existe com SMTP configurado pelo ambiente; texto fixo; link só de `PUBLIC_BASE_URL`; fila sem corpo legível pela aplicação; o worker entrega
por três funções e apaga o corpo; falha de aviso nunca desfaz a mudança. A entrega SMTP é trocada por um dublê (nenhum e-mail real sai)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core import mail
from app.core.db import make_engine
from app.core.security import hash_secret
from app.core.settings import get_settings
from app.workers import mailer
from tests.conftest import SECRET
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session

BASE = "https://olt.example.com"


@pytest.fixture
def smtp_on(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM", "no-reply@example.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def worker_engine(worker_url):
    eng = make_engine(worker_url)
    yield eng
    eng.dispose()


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, role=None, tenant_id=None, email=None):
        email = email or f"e{uuid4().hex[:10]}@example.com"
        with migrated.begin() as c:
            uid = c.execute(text("INSERT INTO users_global(email, display_name, password_hash, is_platform_operator) VALUES (:e,:n,:h,:o) RETURNING id"),
                            {"e": email, "n": f"Pessoa {email[:6]}", "h": hash_secret(PW), "o": operator}).scalar()
            if role:
                c.execute(text("INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (:t,:u,:r)"), {"t": tenant_id, "u": uid, "r": role})
        return {"email": email, "id": uid}
    return create


@pytest.fixture
def operator(client, make):
    who = make(operator=True)
    who["token"] = _with_mfa_session(client, who)["access_token"]
    return who


@pytest.fixture(autouse=True)
def _window(migrated):
    with migrated.begin() as c:
        c.execute(text("UPDATE audit_log SET created_at = created_at - interval '3 hours' WHERE action = 'platform.organization.created' AND created_at > now() - interval '2 hours'"))
        # whatever earlier tests queued must not be claimed by these: this suite owns the queue while it runs
        c.execute(text("UPDATE email_queue SET sent_at = now(), body = NULL WHERE sent_at IS NULL AND failed_at IS NULL"))
    yield


@pytest.fixture
def org(client, operator, make, migrated):
    r, body = _post(client, operator["token"])
    assert r.status_code == 201, r.text
    tid = r.json()["tenant_id"]
    admin = make(role="isp_admin", tenant_id=tid)
    return {"id": tid, "name": body["name"], "admin": admin, "operator": operator}


def _admin_h(client, org):
    return _h(_login(client, org["admin"])["access_token"])


def _queue(migrated, tid):
    with migrated.connect() as c:
        return c.execute(text("SELECT id, kind, to_address, subject, body, sent_at, failed_at, attempts, last_error FROM email_queue WHERE tenant_id = :t ORDER BY created_at, id"), {"t": tid}).all()


# ============================================================ pure: templates and message
def test_templates_are_fixed_clean_and_carry_only_the_link_they_were_given():
    s, b = mail.render("member_invite", organization="Prov\r\nBcc: x@evil.test", link=f"{BASE}/convite/abc", hours=72, actor="Ana\nSilva")
    assert "\n" not in s and "\r" not in s and "Bcc: x@evil.test" in s and s.startswith("Convite para ")   # control characters became blanks: no header can be injected
    assert f"{BASE}/convite/abc" in b and "72 horas" in b
    for kind in ("mfa_reset_notice", "organization_suspended", "organization_reactivated"):
        s2, b2 = mail.render(kind, organization="K3G")
        assert "http" not in b2 and "senha" not in b2.lower().replace("segundo fator", "")   # notices carry no link and no secret
    with pytest.raises(ValueError):
        mail.render("anything_else", organization="x")


def test_the_link_comes_from_the_configured_origin_never_from_the_request(smtp_on):
    assert mail.link_for("tok") == f"{BASE}/convite/tok"


def test_message_has_the_headers_we_set_and_nothing_from_outside(smtp_on):
    m = mail.build_message(get_settings(), "pessoa@example.com", "Assunto", "Corpo")
    assert m["To"] == "pessoa@example.com" and m["Auto-Submitted"] == "auto-generated" and "no-reply@example.com" in m["From"]


def test_settings_refuse_a_plaintext_origin_and_a_bad_sender(monkeypatch):
    from pydantic import ValidationError

    from app.core.settings import Settings
    for var, bad in (("PUBLIC_BASE_URL", "http://olt.example.com"), ("PUBLIC_BASE_URL", "https://x.test/path"), ("SMTP_FROM", "not-an-address"), ("SMTP_SECURITY", "none")):
        monkeypatch.setenv(var, bad)
        with pytest.raises(ValidationError):
            Settings()
        monkeypatch.delenv(var)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:3000")
    assert Settings().public_base_url == "http://localhost:3000"      # a developer's own machine only


# ============================================================ off by default
def test_without_smtp_nothing_is_queued_and_asking_for_email_is_409(client, org, migrated):
    assert mail.enabled() is False
    h = _admin_h(client, org)
    r = client.post("/v1/team/invites", json={"email": "sem.smtp@example.com", "role": "support", "send_email": True}, headers=h)
    assert r.status_code == 409 and r.json() == {"detail": "email_not_configured"}
    ok = client.post("/v1/team/invites", json={"email": "sem.smtp@example.com", "role": "support"}, headers=h)    # the way it always was: the link on screen
    assert ok.status_code == 201 and "emailed" not in ok.json() and ok.json()["token"]
    assert _queue(migrated, org["id"]) == []


# ============================================================ with SMTP: invite, reset, notices
def test_an_invite_can_be_emailed_the_link_waits_in_the_queue_and_the_app_cannot_read_it(client, org, smtp_on, migrated, app_engine):
    h = _admin_h(client, org)
    r = client.post("/v1/team/invites", json={"email": "Nova.Pessoa@Example.com", "role": "support", "send_email": True}, headers=h)
    assert r.status_code == 201 and r.json()["emailed"] is True, r.text
    q = _queue(migrated, org["id"])
    assert len(q) == 1 and q[0].kind == "member_invite" and q[0].to_address == "nova.pessoa@example.com"
    assert f"{BASE}/convite/{r.json()['token']}" in q[0].body and q[0].sent_at is None
    with migrated.connect() as c:
        a = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE tenant_id = :t AND action = 'member.invite.emailed'"), {"t": org["id"]}).all()
    assert len(a) == 1 and "convite/" not in str(a[0][0]) and r.json()["token"] not in str(a[0][0])      # the trail names the address, never the link
    # the application role reads the record but NEVER the body, and cannot change or delete a row
    with app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
        assert c.execute(text("SELECT count(*) FROM email_queue")).scalar() == 1
    for sql in ("SELECT body FROM email_queue", "UPDATE email_queue SET attempts = 0", "DELETE FROM email_queue"):
        with pytest.raises(ProgrammingError), app_engine.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
            c.execute(text(sql))


def test_a_forged_host_header_cannot_redirect_the_link(client, org, smtp_on, migrated):
    h = {**_admin_h(client, org), "Host": "evil.example", "X-Forwarded-Host": "evil.example", "Origin": "https://evil.example"}
    r = client.post("/v1/team/invites", json={"email": "host.forjado@example.com", "role": "support", "send_email": True}, headers=h)
    assert r.status_code == 201, r.text
    body = _queue(migrated, org["id"])[-1].body
    assert f"{BASE}/convite/" in body and "evil.example" not in body


def test_renew_and_password_reset_can_be_emailed_and_the_reset_address_is_the_members_own(client, org, make, smtp_on, migrated):
    h = _admin_h(client, org)
    inv = client.post("/v1/team/invites", json={"email": "renova@example.com", "role": "support"}, headers=h).json()
    r = client.post(f"/v1/team/invites/{inv['id']}/renew?send_email=true", headers=h)
    assert r.status_code == 201 and r.json()["emailed"] is True
    member = make(role="support", tenant_id=org["id"])
    p = client.post(f"/v1/team/members/{member['id']}/password-reset?send_email=true", headers=h)
    assert p.status_code == 201 and p.json()["emailed"] is True, p.text
    q = {x.kind: x for x in _queue(migrated, org["id"])}
    assert q["password_reset"].to_address == member["email"].lower() and "24 horas" in q["password_reset"].body
    nobody = client.post(f"/v1/team/members/{uuid4()}/password-reset?send_email=true", headers=h)
    assert nobody.status_code in (404, 409)


def test_suspension_and_reactivation_notify_the_administrators_and_a_failing_notice_never_undoes_the_change(client, org, make, smtp_on, migrated, monkeypatch):
    other = make(role="isp_admin", tenant_id=org["id"])
    make(role="support", tenant_id=org["id"])                                       # not an administrator: no notice
    op = {"Authorization": f"Bearer {org['operator']['token']}"}
    r = client.post(f"/v1/platform/organizations/{org['id']}/status", json={"status": "suspended", "reason": "Motivo do teste"}, headers=op)
    assert r.status_code == 200 and r.json()["changed"] is True
    q = _queue(migrated, org["id"])
    assert sorted(x.to_address for x in q) == sorted([org["admin"]["email"].lower(), other["email"].lower()]) and {x.kind for x in q} == {"organization_suspended"}
    assert all("Motivo do teste" not in (x.body or "") for x in q)                    # the reason is for the audit trail, not for the mailbox
    again = client.post(f"/v1/platform/organizations/{org['id']}/status", json={"status": "suspended", "reason": "Repetido sem efeito"}, headers=op)
    assert again.json()["changed"] is False and len(_queue(migrated, org["id"])) == 2   # idempotent: no second notice

    def boom(*_a, **_k):
        raise RuntimeError("smtp down is not even involved here: the queue insert fails")
    monkeypatch.setattr(mail, "queue_notice", boom)
    back = client.post(f"/v1/platform/organizations/{org['id']}/status", json={"status": "active", "reason": "Reativar mesmo assim"}, headers=op)
    assert back.status_code == 200 and back.json()["changed"] is True              # the reactivation stands
    assert client.get("/v1/edges", headers=_admin_h(client, org)).status_code == 200


def test_resetting_someones_mfa_tells_them(client, org, make, smtp_on, migrated):
    # the reset route needs the administrator's own MFA: reuse the platform helper to give this administrator one
    sess = _with_mfa_session(client, org["admin"])
    h = _h(sess["access_token"])
    victim = make(role="support", tenant_id=org["id"])
    code = org["admin"]["codes"][0]      # a recovery code of the administrator's own second factor
    r = client.post(f"/v1/members/{victim['id']}/mfa/reset", json={"password": PW, "code": code}, headers=h)
    assert r.status_code == 200, r.text
    q = [x for x in _queue(migrated, org["id"]) if x.kind == "mfa_reset_notice"]
    assert len(q) == 1 and q[0].to_address == victim["email"].lower() and "http" not in q[0].body


# ============================================================ the worker
def _enqueue(migrated, tid, kind="member_invite", to="alvo@example.com", body="Corpo com link https://olt.example.com/convite/tok", ttl="1 hour"):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        return c.execute(text("INSERT INTO email_queue (tenant_id, kind, to_address, subject, body, expires_at) VALUES (:t, :k, :a, 'Assunto', :b, now() + CAST(:ttl AS interval)) RETURNING id"),
                         {"t": tid, "k": kind, "a": to, "b": body, "ttl": ttl}).scalar()


def test_the_worker_delivers_marks_sent_and_erases_the_body(org, smtp_on, migrated, worker_engine):
    mid = _enqueue(migrated, org["id"])
    sent = []
    out = mailer.run_once(worker_engine, get_settings(), deliver=lambda s, to, sub, body: sent.append((to, sub, body)))
    assert out["claimed"] == 1 and out["sent"] == 1 and sent == [("alvo@example.com", "Assunto", "Corpo com link https://olt.example.com/convite/tok")]
    row = [x for x in _queue(migrated, org["id"]) if x.id == mid][0]
    assert row.sent_at is not None and row.body is None and row.last_error is None
    assert mailer.run_once(worker_engine, get_settings(), deliver=lambda *a: sent.append(a))["claimed"] == 0   # nothing is sent twice


def test_a_failing_delivery_is_retried_with_a_backoff_and_gives_up_after_five_erasing_the_body(org, smtp_on, migrated, worker_engine):
    mid = _enqueue(migrated, org["id"])

    def fail(*_a):
        raise ConnectionRefusedError("smtp.example.com:587 recusou para alvo@example.com")
    out = mailer.run_once(worker_engine, get_settings(), deliver=fail)
    assert out["failed"] == 1
    row = [x for x in _queue(migrated, org["id"]) if x.id == mid][0]
    assert row.attempts == 1 and row.last_error == "ConnectionRefusedError" and row.sent_at is None and row.body is not None
    assert "alvo" not in row.last_error and "example" not in row.last_error                                    # only the CLASS is kept
    assert mailer.run_once(worker_engine, get_settings(), deliver=fail)["claimed"] == 0                         # the backoff holds it back
    for _ in range(4):
        with migrated.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
            c.execute(text("UPDATE email_queue SET send_after = now() - interval '1 second' WHERE id = :i"), {"i": mid})
        mailer.run_once(worker_engine, get_settings(), deliver=fail)
    row = [x for x in _queue(migrated, org["id"]) if x.id == mid][0]
    assert row.attempts == 5 and row.failed_at is not None and row.body is None


def test_an_undelivered_link_expires_and_its_body_is_erased_and_old_records_are_purged(org, smtp_on, migrated, worker_engine):
    mid = _enqueue(migrated, org["id"], ttl="1 hour")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
        c.execute(text("UPDATE email_queue SET created_at = now() - interval '3 hours', expires_at = now() - interval '2 hours' WHERE id = :i"), {"i": mid})
    out = mailer.run_once(worker_engine, get_settings(), deliver=lambda *a: pytest.fail("an expired message must not be sent"))
    assert out["claimed"] == 0 and out["expired"] >= 1
    row = [x for x in _queue(migrated, org["id"]) if x.id == mid][0]
    assert row.failed_at is not None and row.body is None and row.last_error == "expired"
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org["id"])})
        c.execute(text("UPDATE email_queue SET created_at = now() - interval '31 days', expires_at = now() - interval '31 days' + interval '1 hour' WHERE id = :i"), {"i": mid})
    assert mailer.run_once(worker_engine, get_settings())["purged"] >= 1
    assert [x for x in _queue(migrated, org["id"]) if x.id == mid] == []


def test_the_worker_role_has_no_access_to_the_table_only_the_three_functions(worker_engine, org):
    for sql in ("SELECT * FROM email_queue", "UPDATE email_queue SET body = 'x'", "DELETE FROM email_queue", "INSERT INTO email_queue (tenant_id) VALUES (NULL)"):
        with pytest.raises(ProgrammingError), worker_engine.begin() as c:
            c.execute(text(sql))
    with worker_engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM app_mail_claim(1)")).scalar() in (0, 1)   # the entry point works


def test_the_application_cannot_call_the_worker_functions(app_engine):
    for sql in ("SELECT * FROM app_mail_claim(1)", "SELECT app_mail_finish(gen_random_uuid(), true, NULL)", "SELECT * FROM app_mail_sweep()"):
        with pytest.raises(ProgrammingError), app_engine.begin() as c:
            c.execute(text(sql))


def test_one_organization_cannot_read_anothers_queue(org, client, operator, make, smtp_on, migrated, app_engine):
    r2, _ = _post(client, operator["token"])
    assert r2.status_code == 201
    other_tid = r2.json()["tenant_id"]
    _enqueue(migrated, org["id"])
    with app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(other_tid)})
        assert c.execute(text("SELECT count(*) FROM email_queue")).scalar() == 0


def test_the_unused_secret_constant_import_is_kept_for_fixtures():
    assert SECRET
