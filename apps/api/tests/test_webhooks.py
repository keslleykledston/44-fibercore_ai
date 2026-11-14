"""Webhooks de saída (ADR-0051 D2, fatia F2): endpoint https com catálogo fechado de eventos, segredo mostrado uma vez e cifrado, carga só com chaves da lista, fan-out do outbox por
organização, entrega assinada, recuo/desligamento por falhas, e a proteção contra SSRF (sem IP literal, só endereço público, conexão ao IP validado, certificado pelo nome, sem redirecionamento)."""
from __future__ import annotations

import datetime as dt
import http.server
import importlib.util
import json
import socket
import ssl
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core import webhooks
from app.core.db import make_engine
from app.core.security import hash_secret
from app.core.settings import get_settings
from app.workers import webhooks as dispatcher
from tests.org_helpers import PW, _h, _login, _post, _with_mfa_session

KEY = Fernet.generate_key().decode()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("WEBHOOK_ENCRYPTION_KEY", KEY)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def app_engine(app_url):
    eng = make_engine(app_url)
    yield eng
    eng.dispose()


@pytest.fixture
def worker_engine(worker_url):
    eng = make_engine(worker_url)
    yield eng
    eng.dispose()


@pytest.fixture
def make(migrated):
    def create(*, operator=False, role=None, tenant_id=None):
        email = f"w{uuid4().hex[:10]}@example.com"
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
        # this suite owns the delivery queue while it runs
        c.execute(text("UPDATE webhook_deliveries SET sent_at = now(), payload = NULL WHERE sent_at IS NULL AND failed_at IS NULL"))
    yield


@pytest.fixture
def two(client, make, migrated):
    op = make(operator=True)
    tok = _with_mfa_session(client, op)["access_token"]
    out = {}
    for k in ("a", "b"):
        r, _ = _post(client, tok)
        assert r.status_code == 201, r.text
        t = r.json()["tenant_id"]
        out[k] = {"id": t, "admin": make(role="isp_admin", tenant_id=t), "eng": make(role="engineer", tenant_id=t)}
    yield out
    with migrated.begin() as c:   # the endpoints of this test must not catch the events of the next one (the fan-out cursor is moved back by `_arm`)
        for k in ("a", "b"):
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": out[k]["id"]})
            c.execute(text("DELETE FROM webhook_endpoints WHERE tenant_id = :t"), {"t": out[k]["id"]})


def _ah(client, org):
    return _h(_login(client, org["admin"])["access_token"])


URL = "https://hooks.example.com/fibercore"


def _mk(client, org, events=("incident.opened",), url=URL, name="Receptor NOC"):
    r = client.post("/v1/webhooks", json={"name": name, "url": url, "events": list(events)}, headers=_ah(client, org))
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================ pure: URL, addresses, signature
@pytest.mark.parametrize("url,code", [
    ("http://hooks.example.com/x", "url_must_be_https"), ("https://127.0.0.1/x", "url_host_must_be_a_name"), ("https://[::1]/x", "url_host_must_be_a_name"),
    ("https://169.254.169.254/latest", "url_host_must_be_a_name"), ("https://10.0.0.5/x", "url_host_must_be_a_name"), ("https://localhost/x", "url_host_not_public"),
    ("https://intranet/x", "url_host_not_public"), ("https://db.internal/x", "url_host_not_public"), ("https://a.local/x", "url_host_not_public"),
    ("https://user:pw@hooks.example.com/x", "url_invalid"), ("https://hooks.example.com:99999/x", "url_invalid"), ("https://hooks.example.com/x#frag", "url_invalid"),
    ("ftp://hooks.example.com/x", "url_must_be_https"), ("https:///x", "url_invalid")])
def test_urls_that_could_aim_inside_are_refused_at_registration(url, code):
    assert webhooks.url_problem(url) == code


def test_a_public_name_and_a_custom_port_are_accepted():
    assert webhooks.url_problem("https://hooks.example.com/a/b?x=1") is None and webhooks.url_problem("https://hooks.example.com:8443/x") is None


@pytest.mark.parametrize("addr,ok", [("8.8.8.8", True), ("2606:4700:4700::1111", True), ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.1", False), ("192.168.1.1", False),
                                     ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False), ("224.0.0.1", False), ("::1", False), ("fe80::1", False), ("fc00::1", False),
                                     ("::ffff:127.0.0.1", False), ("::ffff:10.0.0.1", False), ("2002:7f00:1::1", False), ("::ffff:8.8.8.8", True)])
def test_only_public_addresses_are_ever_connected_to(addr, ok):
    assert webhooks._ip_ok(addr) is ok


def test_a_name_that_mixes_a_public_and_a_private_answer_is_refused_and_a_failing_lookup_is_a_code():
    def mixed(host, port, type=0):
        return [(2, 1, 6, "", ("8.8.8.8", port)), (2, 1, 6, "", ("10.0.0.9", port))]
    with pytest.raises(webhooks.DeliveryError) as e:
        webhooks.resolve_public("hooks.example.com", 443, mixed)
    assert e.value.code == "address_not_public"

    def boom(host, port, type=0):
        raise socket.gaierror("no such host")
    with pytest.raises(webhooks.DeliveryError) as e2:
        webhooks.resolve_public("hooks.example.com", 443, boom)
    assert e2.value.code == "dns_failed"
    assert webhooks.resolve_public("x.example.com", 443, lambda h, p, type=0: [(2, 1, 6, "", ("8.8.8.8", p))]) == ["8.8.8.8"]


def test_the_signature_verifies_rejects_tampering_and_old_timestamps():
    body = b'{"a":1}'
    sig = webhooks.sign("whsec_x", body, now=1_000_000)
    assert webhooks.verify("whsec_x", sig, body, now=1_000_100)
    assert not webhooks.verify("whsec_other", sig, body, now=1_000_100) and not webhooks.verify("whsec_x", sig, body + b" ", now=1_000_100)
    assert not webhooks.verify("whsec_x", sig, body, now=1_000_000 + 301)             # replay outside the tolerance
    assert not webhooks.verify("whsec_x", "garbage", body) and not webhooks.verify("whsec_x", "t=abc,v1=00", body)


def test_catalog_and_migration_agree():
    spec = importlib.util.spec_from_file_location("m0061", Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0061_webhooks.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert tuple(m.EVENTS) == webhooks.EVENTS


# ============================================================ the API
def test_without_a_key_webhooks_do_not_exist(client, two):
    r = client.post("/v1/webhooks", json={"name": "Sem chave", "url": URL, "events": ["incident.opened"]}, headers=_ah(client, two["a"]))
    assert r.status_code == 503 and r.json() == {"detail": "webhooks_unavailable"}
    assert client.get("/v1/webhooks", headers=_ah(client, two["a"])).json()["available"] is False


def test_create_shows_the_secret_once_stores_it_encrypted_and_the_app_cannot_read_it(client, two, on, migrated, app_engine):
    a = two["a"]
    made = _mk(client, a, ("incident.opened", "incident.resolved"))
    assert made["secret"].startswith("whsec_") and made["signature_header"] == "X-FiberCore-Signature"
    lst = client.get("/v1/webhooks", headers=_ah(client, a)).json()
    assert len(lst["items"]) == 1 and "secret" not in str(lst) and made["secret"] not in str(lst) and lst["items"][0]["events"] == ["incident.opened", "incident.resolved"]
    with migrated.connect() as c:
        enc = c.execute(text("SELECT secret_enc FROM webhook_endpoints WHERE id = :i"), {"i": made["id"]}).scalar()
        trail = str(c.execute(text("SELECT evidence_redacted FROM audit_log WHERE tenant_id = :t AND action = 'webhook.created'"), {"t": a["id"]}).all())
    assert made["secret"] not in enc and webhooks.decrypt_secret(get_settings(), enc) == made["secret"]
    assert made["secret"] not in trail and "hooks.example.com" not in trail                      # neither the secret nor the URL is in the trail
    with pytest.raises(ProgrammingError), app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a["id"])})
        c.execute(text("SELECT secret_enc FROM webhook_endpoints"))
    rot = client.post(f"/v1/webhooks/{made['id']}/rotate-secret", headers=_ah(client, a)).json()["secret"]
    assert rot != made["secret"]
    with migrated.connect() as c:
        assert webhooks.decrypt_secret(get_settings(), c.execute(text("SELECT secret_enc FROM webhook_endpoints WHERE id = :i"), {"i": made["id"]}).scalar()) == rot


def test_validation_permissions_limits_and_isolation(client, two, on):
    a, b = two["a"], two["b"]
    h = _ah(client, a)
    for body in ({"name": "Ruim", "url": "http://x.example.com/", "events": ["incident.opened"]}, {"name": "Ruim", "url": "https://10.0.0.1/", "events": ["incident.opened"]},
                 {"name": "Ruim", "url": URL, "events": ["job.dispatched"]}, {"name": "Ruim", "url": URL, "events": []}, {"name": "x", "url": URL, "events": ["incident.opened"]}):
        assert client.post("/v1/webhooks", json=body, headers=h).status_code == 422, body
    eng_h = _h(_login(client, a["eng"])["access_token"])
    assert client.get("/v1/webhooks", headers=eng_h).status_code == 403 and client.post("/v1/webhooks", json={"name": "Nao pode", "url": URL, "events": ["incident.opened"]}, headers=eng_h).status_code == 403
    mine = _mk(client, a)
    assert client.get(f"/v1/webhooks/{mine['id']}/deliveries", headers=_ah(client, b)).status_code == 404       # another organization's endpoint does not exist for me
    assert client.patch(f"/v1/webhooks/{mine['id']}", json={"active": False}, headers=_ah(client, b)).status_code == 404
    assert client.get("/v1/webhooks", headers=_ah(client, b)).json()["items"] == []
    for i in range(webhooks.MAX_ENDPOINTS - 1):
        _mk(client, a, name=f"Receptor {i:02d}")
    over = client.post("/v1/webhooks", json={"name": "Passou", "url": URL, "events": ["incident.opened"]}, headers=h)
    assert over.status_code == 409 and over.json() == {"detail": "webhook_limit"}
    assert client.patch(f"/v1/webhooks/{mine['id']}", json={}, headers=h).status_code == 422
    assert client.patch(f"/v1/webhooks/{mine['id']}", json={"events": ["incident.resolved"], "name": "Renomeado"}, headers=h).json()["events"] == ["incident.resolved"]
    assert client.delete(f"/v1/webhooks/{mine['id']}", headers=h).json() == {"deleted": True} and client.delete(f"/v1/webhooks/{mine['id']}", headers=h).status_code == 404


# ============================================================ the dispatcher
def _event(migrated, tid, etype="incident.opened", age="5 minutes", payload=None):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        return c.execute(text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload, created_at) "
                              "VALUES (:t,'incident',:a,:e,'1',CAST(:p AS jsonb), now() - CAST(:age AS interval)) RETURNING id"),
                         {"t": tid, "a": uuid4(), "e": etype, "p": json.dumps(payload or {"kind": "pon_mass_outage", "pon_path": "0/1/0", "onus_down": 7}), "age": age}).scalar()


def _arm(migrated, worker_engine):
    """Create the fan-out cursor and put it in the past so the events these tests insert are 'new'."""
    with worker_engine.begin() as c:
        c.execute(text("SELECT app_webhook_fanout(1)"))
    with migrated.begin() as c:
        c.execute(text("UPDATE webhook_cursor SET last_created_at = now() - interval '1 hour', last_id = '00000000-0000-0000-0000-000000000000'"))


def _deliveries(migrated, tid):
    with migrated.connect() as c:
        return c.execute(text("SELECT id, endpoint_id, event_id, event_type, payload, sent_at, failed_at, attempts, last_status, last_error FROM webhook_deliveries WHERE tenant_id = :t ORDER BY created_at, id"),
                         {"t": tid}).all()


def test_fanout_makes_one_delivery_per_matching_endpoint_of_that_organization_only_with_a_whitelisted_payload(client, two, on, migrated, worker_engine):
    a, b = two["a"], two["b"]
    ea = _mk(client, a, ("incident.opened",))
    other_event = _mk(client, a, ("incident.resolved",), name="Outro evento")
    off = _mk(client, a, ("incident.opened",), name="Desligado")
    client.patch(f"/v1/webhooks/{off['id']}", json={"active": False}, headers=_ah(client, a))
    eb = _mk(client, b, ("incident.opened",))
    assert ea and other_event and eb
    _arm(migrated, worker_engine)
    ev = _event(migrated, a["id"], payload={"kind": "pon_mass_outage", "pon_path": "0/1/0", "onus_down": 7, "customer_name": "João da Silva", "serial": "HWTC12345678", "members": 4, "secret": "x"})
    _event(migrated, a["id"], etype="job.dispatched")                                                  # not in the catalog
    _event(migrated, a["id"], age="2 seconds")                                                          # too young to be sure the cursor will not pass an uncommitted older row
    with worker_engine.begin() as c:
        assert c.execute(text("SELECT app_webhook_fanout(100)")).scalar() == 1
        assert c.execute(text("SELECT app_webhook_fanout(100)")).scalar() == 0                         # idempotent: the cursor moved
    rows = _deliveries(migrated, a["id"])
    assert len(rows) == 1 and str(rows[0].endpoint_id) == ea["id"] and rows[0].event_id == ev and rows[0].event_type == "incident.opened"
    body = rows[0].payload
    assert set(body) == {"id", "type", "occurred_at", "organization_id", "data"} and body["organization_id"] == str(a["id"])
    assert set(body["data"]) == {"kind", "pon_path", "onus_down", "members", "incident_id"}           # no name, no serial, no secret: only the whitelisted keys
    assert "João" not in json.dumps(body) and "HWTC" not in json.dumps(body)
    assert _deliveries(migrated, b["id"]) == []                                                          # b's endpoint got nothing for a's event


def test_a_delivery_is_signed_sent_and_its_payload_erased(client, two, on, migrated, worker_engine):
    a = two["a"]
    made = _mk(client, a)
    _arm(migrated, worker_engine)
    _event(migrated, a["id"])
    seen = []

    def fake(url, body, headers, **_k):
        seen.append((url, body, headers))
        return 204
    out = dispatcher.run_once(worker_engine, get_settings(), deliver=fake)
    assert out["fanned_out"] == 1 and out["sent"] == 1
    url, body, headers = seen[0]
    assert url == URL and webhooks.verify(made["secret"], headers["X-FiberCore-Signature"], body) and headers["X-FiberCore-Event"] == "incident.opened"
    row = _deliveries(migrated, a["id"])[0]
    assert row.sent_at is not None and row.payload is None and row.last_status == 204
    assert dispatcher.run_once(worker_engine, get_settings(), deliver=fake)["claimed"] == 0                  # nothing is sent twice
    d = client.get(f"/v1/webhooks/{made['id']}/deliveries", headers=_ah(client, a)).json()["items"]
    assert d[0]["state"] == "sent" and d[0]["last_status"] == 204 and "payload" not in d[0]


def test_failures_back_off_record_only_the_class_and_ten_in_a_row_turn_the_endpoint_off(client, two, on, migrated, worker_engine):
    a = two["a"]
    made = _mk(client, a)
    _arm(migrated, worker_engine)

    def refuse(url, body, headers, **_k):
        raise webhooks.DeliveryError("http_error", 503)
    for _ in range(11):
        _event(migrated, a["id"])
    out = dispatcher.run_once(worker_engine, get_settings(), deliver=refuse)
    assert out["failed"] >= 10
    rows = _deliveries(migrated, a["id"])
    assert all(r.last_error == "http_error" and r.last_status == 503 and r.sent_at is None for r in rows if r.attempts)
    ep = client.get("/v1/webhooks", headers=_ah(client, a)).json()["items"][0]
    assert ep["active"] is False and ep["disabled_reason"] == "too_many_failures" and ep["consecutive_failures"] >= 10
    assert dispatcher.run_once(worker_engine, get_settings(), deliver=refuse)["claimed"] == 0           # backoff: nothing is retried at once
    # a person turns it back on: the counter resets
    back = client.patch(f"/v1/webhooks/{made['id']}", json={"active": True}, headers=_ah(client, a)).json()
    assert back["active"] is True and back["consecutive_failures"] == 0 and back["disabled_reason"] is None


def test_a_weird_failure_is_recorded_by_class_never_by_message(client, two, on, migrated, worker_engine):
    a = two["a"]
    _mk(client, a)
    _arm(migrated, worker_engine)
    _event(migrated, a["id"])

    def boom(url, body, headers, **_k):
        raise ValueError("https://hooks.example.com/fibercore?token=SEGREDO deu erro")
    dispatcher.run_once(worker_engine, get_settings(), deliver=boom)
    r = _deliveries(migrated, a["id"])[0]
    assert r.last_error == "ValueError" and "SEGREDO" not in str(r) and "hooks.example.com" not in str(r)


def test_the_test_button_queues_a_harmless_event_even_for_a_paused_endpoint_and_a_deleted_endpoint_takes_its_deliveries(client, two, on, migrated, worker_engine):
    a = two["a"]
    made = _mk(client, a)
    client.patch(f"/v1/webhooks/{made['id']}", json={"active": False}, headers=_ah(client, a))
    assert client.post(f"/v1/webhooks/{made['id']}/test", headers=_ah(client, a)).status_code == 202
    seen = []
    out = dispatcher.run_once(worker_engine, get_settings(), deliver=lambda url, body, headers, **k: seen.append(json.loads(body)) or 200)
    assert out["sent"] == 1 and seen[0]["type"] == "webhook.test" and seen[0]["data"] == {"message": "teste de entrega"}
    assert client.delete(f"/v1/webhooks/{made['id']}", headers=_ah(client, a)).status_code == 200
    assert _deliveries(migrated, a["id"]) == []


def test_an_old_undelivered_event_expires_with_its_payload_erased(client, two, on, migrated, worker_engine):
    a = two["a"]
    _mk(client, a)
    _arm(migrated, worker_engine)
    _event(migrated, a["id"])
    with worker_engine.begin() as c:
        c.execute(text("SELECT app_webhook_fanout(500)"))     # the cursor was moved back an hour: take every older event of the suite too, so ours is surely handled
    assert len(_deliveries(migrated, a["id"])) == 1
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a["id"])})
        c.execute(text("UPDATE webhook_deliveries SET created_at = now() - interval '30 hours', expires_at = now() - interval '6 hours' WHERE tenant_id = :t"), {"t": a["id"]})
    out = dispatcher.run_once(worker_engine, get_settings(), deliver=lambda *a, **k: pytest.fail("an expired delivery must not be sent"))
    assert out["expired"] >= 1
    r = _deliveries(migrated, a["id"])[0]
    assert r.failed_at is not None and r.payload is None and r.last_error == "expired"


def test_roles_the_worker_has_no_table_access_and_the_app_cannot_call_its_functions(worker_engine, app_engine, two):
    for sql in ("SELECT * FROM webhook_endpoints", "SELECT * FROM webhook_deliveries", "UPDATE webhook_endpoints SET active = true", "SELECT * FROM webhook_cursor"):
        with pytest.raises(ProgrammingError), worker_engine.begin() as c:
            c.execute(text(sql))
    for sql in ("SELECT app_webhook_fanout(1)", "SELECT * FROM app_webhook_claim(1)", "SELECT app_webhook_finish(gen_random_uuid(), true, 200, NULL)", "SELECT * FROM app_webhook_sweep()"):
        with pytest.raises(ProgrammingError), app_engine.begin() as c:
            c.execute(text(sql))


# ============================================================ the real delivery: a local TLS receiver
@pytest.fixture
def tls_server(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False).sign(key, hashes.SHA256()))
    cert_pem, key_pem = tmp_path / "c.pem", tmp_path / "k.pem"
    cert_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    got: list = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):   # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            got.append({"path": self.path, "host": self.headers.get("Host"), "headers": dict(self.headers), "body": body})
            if self.path == "/redirect":
                self.send_response(302); self.send_header("Location", "https://evil.example/"); self.end_headers(); return   # noqa: E702
            self.send_response(200 if self.path != "/boom" else 500); self.end_headers(); self.wfile.write(b"ok")   # noqa: E702

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_pem, key_pem)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    client_ctx = ssl.create_default_context(cafile=str(cert_pem))
    yield {"port": srv.server_address[1], "got": got, "ctx": client_ctx, "cert": cert_pem}
    srv.shutdown()


def test_a_real_delivery_connects_to_the_pinned_address_verifies_the_certificate_by_name_and_signs(tls_server):
    body = b'{"type":"webhook.test"}'
    headers = {"Content-Type": "application/json", webhooks.SIGNATURE_HEADER: webhooks.sign("whsec_t", body)}
    status = webhooks.deliver(f"https://localhost:{tls_server['port']}/hook", body, headers, context=tls_server["ctx"], allow_private=True)
    assert status == 200
    g = tls_server["got"][0]
    assert g["path"] == "/hook" and g["body"] == body and g["host"] == f"localhost:{tls_server['port']}" and webhooks.verify("whsec_t", g["headers"][webhooks.SIGNATURE_HEADER], g["body"])


def test_redirects_are_not_followed_errors_are_codes_and_a_certificate_for_another_name_fails(tls_server):
    with pytest.raises(webhooks.DeliveryError) as e:
        webhooks.deliver(f"https://localhost:{tls_server['port']}/redirect", b"{}", {}, context=tls_server["ctx"], allow_private=True)
    assert e.value.code == "redirect_not_followed" and e.value.status == 302 and len(tls_server["got"]) == 1       # the Location was never requested
    with pytest.raises(webhooks.DeliveryError) as e2:
        webhooks.deliver(f"https://localhost:{tls_server['port']}/boom", b"{}", {}, context=tls_server["ctx"], allow_private=True)
    assert (e2.value.code, e2.value.status) == ("http_error", 500)
    default_ctx = ssl.create_default_context()                                                                        # the system CAs do not know this certificate
    with pytest.raises(webhooks.DeliveryError) as e3:
        webhooks.deliver(f"https://localhost:{tls_server['port']}/hook", b"{}", {}, context=default_ctx, allow_private=True)
    assert e3.value.code == "tls_failed"


def test_without_the_test_overrides_loopback_and_private_names_never_connect(tls_server):
    for url in (f"https://localhost:{tls_server['port']}/hook", "https://127.0.0.1/hook", "https://169.254.169.254/latest/meta-data/"):
        with pytest.raises(webhooks.DeliveryError):
            webhooks.deliver(url, b"{}", {})
    assert len(tls_server["got"]) == 0
    with pytest.raises(webhooks.DeliveryError) as e:                                         # a public-looking name that RESOLVES to loopback: refused after resolution
        webhooks.deliver("https://innocent.example.com/hook", b"{}", {}, resolver=lambda h, p, type=0: [(2, 1, 6, "", ("127.0.0.1", p))])
    assert e.value.code == "address_not_public"
    with pytest.raises(webhooks.DeliveryError) as e2:
        webhooks.deliver("https://hooks.example.com/hook", b"x" * (webhooks.MAX_BODY + 1), {})
    assert e2.value.code == "body_too_large"
