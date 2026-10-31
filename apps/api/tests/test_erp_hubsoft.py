"""ERP Hub, HubSoft first (ADR-0033, HS-01 + HS-02): the connection registry, the secret reference, the URL/host guard, the OAuth token with its cache and failure
policy, and the API. Everything runs against MOCKS: nothing here is evidence that an HubSoft instance works (that needs an authorised, real, read-only test)."""
from __future__ import annotations

import json
import os
import threading
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from app.api import erp_connections
from app.core import erp_hub
from app.core.erp_hub import Credentials, normalize_base_url
from app.core.settings import get_settings
from app.integrations import hubsoft
from app.integrations.hubsoft import HubSoftClient, HubSoftError, Policy, Raw, TokenCache
from tests.conftest import hdr

ALLOWED = ("erp.example.com", "*.hubsoft.test")
TENANT = UUID("11111111-1111-1111-1111-111111111111")
SECRET_VALUE = "s3cr3t-value-never-seen-0123456789"


# ---------------------------------------------------------------- registry and URL guard ----------------------------------------------------------------
def test_only_hubsoft_has_a_connector_and_the_order_is_hubsoft_ixc_sgp():
    assert erp_hub.HOMOLOGATION_ORDER == ("hubsoft", "ixc", "sgp")
    assert {k: v.real_connector for k, v in erp_hub.PROVIDERS.items()} == {"hubsoft": True, "ixc": False, "sgp": False}
    assert all(p.integration_status != "homologated" for p in erp_hub.PROVIDERS.values())   # homologation is a recorded fact, never a code constant
    ok = ("hubsoft", "hubsoft_oauth_credentials", "cloud", "lookup_only", "hubsoft-lab")
    assert erp_hub.validate_connection(*ok).id == "hubsoft"
    for bad, code in [(("ixc", "ixc_user_api_token", "cloud", "lookup_only", "ixc-lab"), "provider_not_available"),
                      (("sgp", "sgp_v1_bearer_explicit", "cloud", "lookup_only", "sgp-lab"), "provider_not_available"),
                      (("zzz", "x", "cloud", "lookup_only", "abc"), "unknown_provider"),
                      (("hubsoft", "ixc_user_api_token", "cloud", "lookup_only", "hubsoft-lab"), "auth_profile_not_supported"),
                      (("hubsoft", "hubsoft_oauth_credentials", "edge", "lookup_only", "hubsoft-lab"), "transport_not_available"),
                      (("hubsoft", "hubsoft_oauth_credentials", "cloud", "incremental", "hubsoft-lab"), "sync_mode_not_supported"),
                      (("hubsoft", "hubsoft_oauth_credentials", "cloud", "snapshot", "hubsoft-lab"), "sync_mode_not_supported"),
                      (("hubsoft", "hubsoft_oauth_credentials", "cloud", "lookup_only", "../etc/passwd"), "secret_ref_invalid"),
                      (("hubsoft", "hubsoft_oauth_credentials", "cloud", "lookup_only", "AB"), "secret_ref_invalid")]:
        with pytest.raises(erp_hub.ConnectionInvalid, match=code):
            erp_hub.validate_connection(*bad)


def test_the_base_url_must_be_https_a_dns_name_on_the_allowlist_and_nothing_more():
    assert normalize_base_url("https://erp.example.com", ALLOWED) == "https://erp.example.com"
    assert normalize_base_url("https://ERP.Example.com/", ALLOWED) == "https://erp.example.com"
    assert normalize_base_url("https://acme.hubsoft.test:443", ALLOWED) == "https://acme.hubsoft.test"
    for bad in ["http://erp.example.com", "https://user:pw@erp.example.com", "https://erp.example.com:8443", "https://erp.example.com/api", "https://erp.example.com/?x=1",
                "https://erp.example.com/#f", "https://127.0.0.1", "https://[::1]", "https://10.0.0.5", "https://localhost", "https://intranet", "ftp://erp.example.com", "//erp.example.com",
                "https://erp.example.com\n", "https://erp .example.com", "", "https://-bad.example.com"]:
        with pytest.raises(erp_hub.ConnectionInvalid, match="base_url_invalid"):
            normalize_base_url(bad, ALLOWED)
    for off in ["https://other.example.com", "https://hubsoft.test", "https://evilhubsoft.test", "https://erp.example.com.evil.test"]:
        with pytest.raises(erp_hub.ConnectionInvalid, match="base_url_not_allowed"):
            normalize_base_url(off, ALLOWED)
    with pytest.raises(erp_hub.ConnectionInvalid, match="base_url_not_allowed"):
        normalize_base_url("https://erp.example.com", ())   # an empty allowlist allows nothing


def test_a_name_that_resolves_to_anything_but_public_addresses_is_refused_whole():
    assert erp_hub.resolve_public("h", lambda h: ["93.184.216.34"]) == ["93.184.216.34"]
    assert erp_hub.resolve_public("h", lambda h: ["2606:2800:220:1:248:1893:25c8:1946"]) == ["2606:2800:220:1:248:1893:25c8:1946"]
    for bad in (
        ["127.0.0.1"], ["10.1.2.3"], ["192.168.0.9"], ["172.16.0.1"], ["169.254.169.254"], ["100.64.0.1"], ["0" + ".0.0.0"], ["::1"], ["fe80::1"], ["fc00::1"], ["224.0.0.1"],
        ["93.184.216.34", "10.0.0.1"], ["::ffff:10.0.0.1"], ["not-an-ip"]):
        with pytest.raises(erp_hub.ConnectionInvalid, match="host_not_public"):
            erp_hub.resolve_public("h", lambda h, bad=bad: bad)
    for empty in ([], ):
        with pytest.raises(erp_hub.ConnectionInvalid, match="host_unresolvable"):
            erp_hub.resolve_public("h", lambda h, e=empty: e)

    def boom(h):
        raise OSError("dns")
    with pytest.raises(erp_hub.ConnectionInvalid, match="host_unresolvable"):
        erp_hub.resolve_public("h", boom)


# ---------------------------------------------------------------- the secret reference ----------------------------------------------------------------
def _put_secret(tmp_path, tenant, ref="hubsoft-lab", data=None, mode=0o600):
    d = tmp_path / str(tenant)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{ref}.json"
    f.write_text(json.dumps(data or {"client_id": "cid", "client_secret": SECRET_VALUE, "username": "svc", "password": "pw-" + SECRET_VALUE}))
    os.chmod(f, mode)
    return f


def test_credentials_come_from_the_tenants_own_file_and_nothing_else(tmp_path):
    f = _put_secret(tmp_path, TENANT)
    c = erp_hub.load_credentials(str(tmp_path), TENANT, "hubsoft-lab")
    assert (c.client_id, c.username) == ("cid", "svc") and len(c.version) == 16
    assert SECRET_VALUE not in repr(c) and "pw-" not in repr(c)   # the dataclass never prints a secret
    # a rotated secret is a new cache key
    f.write_text(json.dumps({"client_id": "cid", "client_secret": "other-secret-value-xyz", "username": "svc", "password": "p2"}))
    os.chmod(f, 0o600)
    assert erp_hub.load_credentials(str(tmp_path), TENANT, "hubsoft-lab").version != c.version
    # another tenant does not see it; neither does a path trick
    with pytest.raises(erp_hub.SecretError) as e:
        erp_hub.load_credentials(str(tmp_path), uuid4(), "hubsoft-lab")
    assert e.value.code == "secret_not_found"
    for ref in ("../x", "a/b", "ab", "A" * 10, ""):
        with pytest.raises(erp_hub.SecretError):
            erp_hub.load_credentials(str(tmp_path), TENANT, ref)
    with pytest.raises(erp_hub.SecretError):
        erp_hub.load_credentials("", TENANT, "hubsoft-lab")


def test_a_secret_file_that_is_readable_by_others_a_symlink_or_malformed_is_refused(tmp_path):
    f = _put_secret(tmp_path, TENANT, mode=0o640)
    with pytest.raises(erp_hub.SecretError) as e:
        erp_hub.load_credentials(str(tmp_path), TENANT, "hubsoft-lab")
    assert e.value.code == "secret_permissions"
    os.chmod(f, 0o600)
    link = tmp_path / str(TENANT) / "linked.json"
    link.symlink_to(f)
    with pytest.raises(erp_hub.SecretError) as e:
        erp_hub.load_credentials(str(tmp_path), TENANT, "linked")
    assert e.value.code == "secret_not_found"
    for bad in ({"client_id": "a", "client_secret": "b", "username": "c"}, {"client_id": "a", "client_secret": "b", "username": "c", "password": "d", "extra": "e"},
                {"client_id": "a", "client_secret": "", "username": "c", "password": "d"}, {"client_id": 1, "client_secret": "b", "username": "c", "password": "d"}):
        f.write_text(json.dumps(bad))
        os.chmod(f, 0o600)
        with pytest.raises(erp_hub.SecretError) as e:
            erp_hub.load_credentials(str(tmp_path), TENANT, "hubsoft-lab")
        assert e.value.code == "secret_invalid"
    f.write_text("{not json")
    os.chmod(f, 0o600)
    with pytest.raises(erp_hub.SecretError, match="secret_invalid"):
        erp_hub.load_credentials(str(tmp_path), TENANT, "hubsoft-lab")


# ---------------------------------------------------------------- the token client ----------------------------------------------------------------
class Net:
    """A scripted HubSoft: each call to send() pops the next answer for its path; every call is recorded (method, path, headers, body)."""

    def __init__(self, *answers: Raw | Exception):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, path, headers, body, params):
        self.calls.append((method, path, dict(headers), body, params))
        a = self.answers.pop(0) if self.answers else Raw(500, {}, b"")
        if isinstance(a, Exception):
            raise a
        return a


def tok(token="tok-0123456789", ttl=3600) -> Raw:  # noqa: S107
    return Raw(200, {}, json.dumps({"access_token": token, "token_type": "Bearer", "expires_in": ttl}).encode())


def ok(data=None) -> Raw:
    return Raw(200, {}, json.dumps(data if data is not None else {"ok": True}).encode())


def status(code, body=b"", **headers) -> Raw:
    return Raw(code, {k.replace("_", "-"): v for k, v in headers.items()}, body)


class Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def client(net, clock=None, policy=None, key=None, creds=None, **kw):
    clock = clock or Clock()
    return HubSoftClient(creds=creds or Credentials("cid", SECRET_VALUE, "svc", "pw-" + SECRET_VALUE, "v1"), key=key or ("t", "c", "h", "v1"), send=net, policy=policy or Policy(),
                         cache=TokenCache(), clock=clock, sleep=clock.sleep, rng=lambda: 0.5, **kw), clock


def test_the_token_is_requested_once_cached_and_used_as_a_bearer():
    net = Net(tok(), ok({"n": 1}), ok({"n": 2}), ok({"n": 3}))
    c, _ = client(net)
    assert [c.get("/api/v1/integracao/cliente", {"x": "1"})["n"] for _ in range(3)] == [1, 2, 3]
    assert c.auth_calls == 1
    method, path, headers, body, _ = net.calls[0]
    assert (method, path) == ("POST", "/oauth/token") and body["grant_type"] == "password" and set(body) == {"client_id", "client_secret", "username", "password", "grant_type"}
    assert all(call[2]["Authorization"] == "Bearer tok-0123456789" for call in net.calls[1:]) and all(call[0] == "GET" for call in net.calls[1:])


def test_the_token_is_renewed_shortly_before_expires_in_and_not_before():
    net = Net(tok("tok-aaaaaaaa", 100), ok(), tok("tok-bbbbbbbb", 100), ok())
    c, clock = client(net)
    c.get("/p")
    clock.t += 60                       # 100 s lifetime, 30 s margin: still valid at 60 s
    assert c.token() == "tok-aaaaaaaa" and c.auth_calls == 1
    clock.t += 15                       # 75 s > 70 s: renew
    c.get("/p")
    assert c.auth_calls == 2 and net.calls[-1][2]["Authorization"] == "Bearer tok-bbbbbbbb"


def test_a_401_on_a_request_authenticates_once_more_and_a_second_401_is_final():
    net = Net(tok("tok-aaaaaaaa"), status(401), tok("tok-bbbbbbbb"), ok({"fine": 1}))
    c, _ = client(net)
    assert c.get("/p") == {"fine": 1} and c.auth_calls == 2
    net2 = Net(tok("tok-aaaaaaaa"), status(401), tok("tok-bbbbbbbb"), status(401), tok("never-used-xx"))
    c2, _ = client(net2)
    with pytest.raises(HubSoftError) as e:
        c2.get("/p")
    assert e.value.code == "INVALID_AUTH" and c2.auth_calls == 2 and len(net2.answers) == 1   # no third attempt


def test_wrong_credentials_and_forbidden_are_final_and_never_retried():
    for answer, code in [(status(401), "INVALID_AUTH"), (status(403), "FORBIDDEN"), (status(400, b'{"error":"invalid_grant"}'), "INVALID_AUTH"),
                         (status(400, b'{"error":"invalid_client"}'), "INVALID_AUTH"), (status(400, b'{"error":"invalid_request"}'), "BAD_REQUEST")]:
        net = Net(answer, tok())
        c, clock = client(net)
        with pytest.raises(HubSoftError) as e:
            c.token()
        assert e.value.code == code and len(net.calls) == 1 and not clock.slept
    assert HubSoftError("INVALID_AUTH").state == "unauthorized" and HubSoftError("FORBIDDEN").state == "unauthorized"


def test_429_waits_a_short_retry_after_once_and_reports_a_long_one():
    net = Net(tok(), status(429, retry_after="2"), ok({"a": 1}))
    c, clock = client(net)
    assert c.get("/p") == {"a": 1}
    assert any(2.0 <= s < 2.2 for s in clock.slept)
    body = Net(tok(), status(429, json.dumps({"retry_after": 3}).encode()), ok({"a": 2}))     # the value may also come in the body
    c2, clock2 = client(body)
    assert c2.get("/p") == {"a": 2} and any(3.0 <= s < 3.2 for s in clock2.slept)
    long = Net(tok(), status(429, retry_after="60"), ok())
    c3, clock3 = client(long)
    with pytest.raises(HubSoftError) as e:
        c3.get("/p")
    assert (e.value.code, e.value.retry_after, e.value.state) == ("RATE_LIMITED", 60.0, "rate_limited") and not any(s > 5 for s in clock3.slept) and len(long.calls) == 2
    twice = Net(tok(), status(429, retry_after="1"), status(429, retry_after="1"), ok())
    c4, _ = client(twice)
    with pytest.raises(HubSoftError, match="RATE_LIMITED"):
        c4.get("/p")
    assert len(twice.calls) == 3   # one wait, then report: no loop
    nohint = Net(tok(), status(429))
    c5, _ = client(nohint)
    with pytest.raises(HubSoftError, match="RATE_LIMITED"):
        c5.get("/p")


def test_5xx_and_network_errors_are_retried_a_bounded_number_of_times_with_jitter():
    net = Net(tok(), status(503), HubSoftError("TEMPORARILY_UNAVAILABLE"), ok({"b": 1}))
    c, clock = client(net)
    assert c.get("/p") == {"b": 1} and len(clock.slept) == 2 and all(s > 0 for s in clock.slept)
    dead = Net(tok(), status(502), status(502), status(502), ok())
    c2, clock2 = client(dead)
    with pytest.raises(HubSoftError) as e:
        c2.get("/p")
    assert (e.value.code, e.value.state) == ("TEMPORARILY_UNAVAILABLE", "offline") and len(dead.calls) == 4 and len(clock2.slept) == 2   # token + 1 try + 2 retries


def test_a_redirect_is_never_followed_and_a_bad_token_answer_is_never_cached():
    net = Net(status(302, b"", location="https://elsewhere.test/oauth/token"))
    c, _ = client(net)
    with pytest.raises(HubSoftError, match="BAD_RESPONSE"):
        c.token()
    for bad in (b"not json", b"[]", b'{"access_token":"short","expires_in":3600}', b'{"access_token":"tok-0123456789"}', b'{"access_token":"tok-0123456789","expires_in":true}',
                b'{"access_token":"tok-0123456789","expires_in":0}', b'{"access_token":"tok-0123456789","expires_in":99999999999}', b'{"access_token":12345678,"expires_in":10}'):
        n = Net(Raw(200, {}, bad), tok())
        cc, _ = client(n)
        with pytest.raises(HubSoftError, match="BAD_RESPONSE"):
            cc.token()
        assert cc.cache.get(cc.key, cc.clock()) is None
    n2 = Net(ok({"x": 1}), tok())
    cc2, _ = client(n2)
    with pytest.raises(HubSoftError, match="BAD_RESPONSE"):   # a 200 without a token answer where the token was expected
        cc2.token()


def test_our_own_limiters_keep_us_under_the_vendors_limit():
    net = Net(*[tok() for _ in range(10)])
    c, clock = client(net, policy=Policy(auth_per_minute=6.0, auth_burst=2))
    for _ in range(2):
        c.cache.drop(c.key)
        c.token()
    c.cache.drop(c.key)
    with pytest.raises(HubSoftError) as e:   # the third authentication within the window would need a 10 s wait: refused locally, nothing is sent
        c.token()
    assert e.value.code == "RATE_LIMITED" and len(net.calls) == 2 and not clock.slept
    fast = Net(tok(), *[ok() for _ in range(6)])
    c2, clock2 = client(fast, policy=Policy(request_per_second=2.0, request_burst=2))
    for _ in range(6):
        c2.get("/p")
    assert sum(clock2.slept) >= 1.5     # past the burst, the 2/s pace is enforced by waiting


def test_concurrent_callers_of_one_connection_share_one_authentication():
    gate, seen = threading.Event(), []

    def send(method, path, headers, body, params):
        if path == "/oauth/token":
            seen.append(1)
            gate.wait(0.3)
            return tok()
        return ok()
    c = HubSoftClient(creds=Credentials("c", "s", "u", "p", "v"), key=("t", "c", "h", "v"), send=send, cache=TokenCache())
    ts = [threading.Thread(target=lambda: c.get("/p")) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(seen) == 1


def test_tokens_are_not_shared_between_tenants_connections_hosts_or_credential_versions():
    cache = TokenCache()
    mk = lambda key, t: HubSoftClient(creds=Credentials("c", "s", "u", "p", "v"), key=key, send=Net(tok(t), ok()), cache=cache)   # noqa: E731
    a, b = mk(("t1", "c1", "h", "v1"), "tok-for-tenant-1"), mk(("t2", "c1", "h", "v1"), "tok-for-tenant-2")
    assert a.token() == "tok-for-tenant-1" and b.token() == "tok-for-tenant-2"
    for other in (("t1", "c2", "h", "v1"), ("t1", "c1", "h2", "v1"), ("t1", "c1", "h", "v2")):
        assert mk(other, "tok-for-other-key").token() == "tok-for-other-key"


def test_no_secret_or_token_appears_in_an_error_or_a_repr():
    net = Net(status(401, SECRET_VALUE.encode()))
    c, _ = client(net)
    with pytest.raises(HubSoftError) as e:
        c.token()
    blob = repr(e.value) + str(e.value) + repr(c) + repr(c.creds)
    assert SECRET_VALUE not in blob and "pw-" not in blob


def test_test_connection_authenticates_with_the_credentials_even_when_a_token_is_cached():
    net = Net(tok("tok-aaaaaaaa"), tok("tok-bbbbbbbb"))
    c, _ = client(net)
    c.token()
    hubsoft.test_connection(c)
    assert c.auth_calls == 2 and [x[1] for x in net.calls] == ["/oauth/token", "/oauth/token"]   # nothing but authentication is ever called


# ---------------------------------------------------------------- the real HTTP sender ----------------------------------------------------------------
def test_the_sender_connects_to_the_checked_address_keeps_the_name_for_tls_and_never_follows_redirects():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx.Response(302, headers={"location": "https://169.254.169.254/"}, content=b"")
    send = hubsoft.make_send("erp.example.com", ["93.184.216.34"], transport=httpx.MockTransport(handler))
    raw = send("GET", "/api/v1/x", {"Accept": "application/json"}, None, {"a": "b"})
    assert raw.status == 302 and len(seen) == 1     # the redirect target was never contacted
    assert seen[0][0].startswith("https://93.184.216.34/api/v1/x") and seen[0][1] == "erp.example.com" and seen[0][2] == "erp.example.com"
    v6 = []
    hubsoft.make_send("erp.example.com", ["2606:2800::1"], transport=httpx.MockTransport(lambda r: (v6.append(str(r.url)), httpx.Response(200, content=b"{}"))[1]))("GET", "/p", {}, None, None)
    assert v6[0].startswith("https://[2606:2800::1]/p")


def test_the_sender_tries_the_next_address_then_reports_unavailable_and_caps_the_body():
    order = []

    def handler(request):
        order.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise httpx.ConnectError("down")
        return httpx.Response(200, content=b'{"ok":1}')
    assert hubsoft.make_send("h.example.com", ["93.184.216.34", "93.184.216.35"], transport=httpx.MockTransport(handler))("GET", "/p", {}, None, None).status == 200
    assert order == ["93.184.216.34", "93.184.216.35"]
    with pytest.raises(HubSoftError, match="TEMPORARILY_UNAVAILABLE"):
        hubsoft.make_send("h.example.com", ["93.184.216.34"], transport=httpx.MockTransport(handler))("GET", "/p", {}, None, None)
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (hubsoft.MAX_BODY + 10)))
    with pytest.raises(HubSoftError, match="BAD_RESPONSE"):
        hubsoft.make_send("h.example.com", ["93.184.216.34"], transport=big)("GET", "/p", {}, None, None)


# ---------------------------------------------------------------- the API ----------------------------------------------------------------
@pytest.fixture
def env(migrated, seed, tmp_path, monkeypatch):
    from app.main import app
    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(update={"erp_secrets_dir": str(tmp_path), "erp_allowed_hosts": "erp.example.com,*.hubsoft.test", "erp_auth_per_minute": 25})
    monkeypatch.setattr(erp_connections, "TEST_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(erp_connections, "_resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(erp_connections, "_client_options", lambda: {"sleep": lambda s: None})
    erp_connections._LIMITERS.clear()
    hubsoft.CACHE.clear()
    with migrated.begin() as c:
        c.execute(text("DELETE FROM erp_egress_budget"))
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,'erp_hubsoft',true) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = true"), {"t": seed["A"]})
    yield tmp_path
    app.dependency_overrides.pop(get_settings, None)
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("DELETE FROM tenant_features WHERE tenant_id = :t AND feature = 'erp_hubsoft'"), {"t": seed["A"]})
        c.execute(text("DELETE FROM erp_connections"))


def body(**kw):
    return {"provider": "hubsoft", "display_name": f"HubSoft {uuid4().hex[:6]}", "auth_profile": "hubsoft_oauth_credentials", "base_url": "https://erp.example.com", "secret_ref": "hubsoft-lab", **kw}


def create(client, h, **kw):
    r = client.post("/v1/integrations/erp", headers=h, json=body(**kw))
    assert r.status_code == 201, r.text
    return r.json()


def net_for(monkeypatch, net):
    monkeypatch.setattr(erp_connections, "_send_for", lambda host, addrs: net)
    return net


def test_nothing_can_be_created_while_the_tenant_flag_is_off(client, seed, env, migrated):
    h = hdr(client, "alice", seed, "A")
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE tenant_id = :t AND feature = 'erp_hubsoft'"), {"t": seed["A"]})
    assert client.post("/v1/integrations/erp", headers=h, json=body()).status_code == 403
    listing = client.get("/v1/integrations/erp", headers=h).json()
    assert listing["enabled"] is False and listing["items"] == [] and [p["id"] for p in listing["providers"]] == ["hubsoft", "ixc", "sgp"]


def test_create_validates_and_never_returns_or_stores_a_secret(client, seed, env, migrated):
    h = hdr(client, "alice", seed, "A")
    made = create(client, h)
    assert made["status"] == "unconfigured" and made["enabled"] is False and made["sync_mode"] == "lookup_only" and made["host"] == "erp.example.com"
    assert "secret_ref" not in made and "secret" not in json.dumps(made).lower().replace("secret_ref", "")
    with migrated.begin() as c:
        row = c.execute(text("SELECT secret_ref, base_url FROM erp_connections WHERE id = :i"), {"i": made["id"]}).first()
        ev = c.execute(text("SELECT evidence_redacted FROM audit_log WHERE action = 'erp.connection.created' AND target_id = :i"), {"i": made["id"]}).scalar()
    assert row.secret_ref == "hubsoft-lab" and row.base_url == "https://erp.example.com" and ev == {"provider": "hubsoft", "host": "erp.example.com"}
    for kw, code, status_code in [({"provider": "ixc", "auth_profile": "ixc_user_api_token"}, "provider_not_available", 422), ({"provider": "sgp", "auth_profile": "sgp_v1_bearer_explicit"}, "provider_not_available", 422),
                                  ({"base_url": "http://erp.example.com"}, "base_url_invalid", 422), ({"base_url": "https://127.0.0.1"}, "base_url_invalid", 422),
                                  ({"base_url": "https://evil.example.org"}, "base_url_not_allowed", 422), ({"secret_ref": "../../etc/passwd"}, "secret_ref_invalid", 422),
                                  ({"transport_mode": "edge"}, "transport_not_available", 422), ({"sync_mode": "snapshot"}, "sync_mode_not_supported", 422)]:
        r = client.post("/v1/integrations/erp", headers=h, json=body(**kw))
        assert (r.status_code, r.json()["detail"]) == (status_code, code), (kw, r.text)
    dup = client.post("/v1/integrations/erp", headers=h, json=body(display_name=made["display_name"]))
    assert dup.status_code == 409
    assert client.post("/v1/integrations/erp", headers=h, json={**body(), "client_secret": "x"}).status_code == 201   # unknown fields are dropped, never stored


def test_only_roles_with_the_permissions_can_use_it_and_tenants_are_isolated(client, seed, env):
    a, b = hdr(client, "alice", seed, "A"), hdr(client, "bob", seed, "B")
    made = create(client, a)
    for who in ("carol", "dave"):
        h = hdr(client, who, seed, "A")
        assert client.get("/v1/integrations/erp", headers=h).status_code == 403
        assert client.post("/v1/integrations/erp", headers=h, json=body()).status_code == 403
        assert client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h).status_code == 403
    assert client.get("/v1/integrations/erp", headers=b).json()["items"] == []
    for op in ("test", "enable", "disable"):
        assert client.post(f"/v1/integrations/erp/{made['id']}/{op}", headers=b).status_code in (403, 404)   # B's flag is off (403) or the row is invisible (404): never A's data


def test_the_test_reports_a_missing_secret_without_calling_the_erp(client, seed, env, monkeypatch):
    h = hdr(client, "alice", seed, "A")
    net = net_for(monkeypatch, Net(tok()))
    made = create(client, h)
    r = client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h)
    assert r.status_code == 200 and (r.json()["status"], r.json()["last_error_class"]) == ("unconfigured", "SECRET_NOT_FOUND") and net.calls == []


def test_a_good_test_marks_the_connection_healthy_and_a_rejected_one_unauthorized_or_rate_limited(client, seed, env, monkeypatch):
    h = hdr(client, "alice", seed, "A")
    made = create(client, h)
    _put_secret(env, seed["A"])
    net = net_for(monkeypatch, Net(tok()))
    r = client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h).json()
    assert (r["status"], r["last_error_class"]) == ("healthy", None) and r["last_success_at"] and [c[1] for c in net.calls] == ["/oauth/token"]
    assert net.calls[0][3]["client_secret"] == SECRET_VALUE      # the secret reached the vendor, and only there
    for answer, status_name, cls in [(status(401), "unauthorized", "INVALID_AUTH"), (status(403), "unauthorized", "FORBIDDEN"), (status(429, retry_after="60"), "rate_limited", "RATE_LIMITED"),
                                     (status(503), "offline", "TEMPORARILY_UNAVAILABLE"), (Raw(200, {}, b"{}"), "degraded", "BAD_RESPONSE")]:
        erp_connections._LIMITERS.clear()
        net_for(monkeypatch, Net(answer, answer, answer, answer))
        r = client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h).json()
        assert (r["status"], r["last_error_class"]) == (status_name, cls), answer
        assert r["last_success_at"]                              # the earlier success is kept as history


def test_the_test_refuses_a_name_that_resolves_to_a_private_address(client, seed, env, monkeypatch):
    h = hdr(client, "alice", seed, "A")
    made = create(client, h)
    _put_secret(env, seed["A"])
    net = net_for(monkeypatch, Net(tok()))
    monkeypatch.setattr(erp_connections, "_resolve", lambda host: erp_hub.resolve_public(host, lambda x: ["10.0.0.7"]))
    r = client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h).json()
    assert (r["status"], r["last_error_class"]) == ("degraded", "HOST_NOT_PUBLIC") and net.calls == []


def test_tests_of_one_connection_are_spaced_and_the_secret_never_reaches_a_response_log_or_audit(client, seed, env, monkeypatch, caplog, migrated):
    h = hdr(client, "alice", seed, "A")
    made = create(client, h)
    _put_secret(env, seed["A"])
    monkeypatch.setattr(erp_connections, "TEST_MIN_INTERVAL_S", 600)
    net_for(monkeypatch, Net(status(401, SECRET_VALUE.encode())))
    with caplog.at_level("DEBUG"):
        first = client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h)
        second = client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h)
    assert first.status_code == 200 and second.status_code == 429 and second.json()["detail"] == "test_too_soon"
    with migrated.begin() as c:
        audit = json.dumps([r[0] for r in c.execute(text("SELECT evidence_redacted FROM audit_log WHERE action LIKE 'erp.%'"))])
    for blob in (first.text, second.text, caplog.text, audit):
        assert SECRET_VALUE not in blob and "pw-" not in blob


def test_enable_needs_a_healthy_test_and_disable_always_works(client, seed, env, monkeypatch, migrated):
    h = hdr(client, "alice", seed, "A")
    made = create(client, h)
    assert client.post(f"/v1/integrations/erp/{made['id']}/enable", headers=h).json()["detail"] == "test_first"
    _put_secret(env, seed["A"])
    net_for(monkeypatch, Net(tok()))
    assert client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h).json()["status"] == "healthy"
    on = client.post(f"/v1/integrations/erp/{made['id']}/enable", headers=h).json()
    assert on["enabled"] is True
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        c.execute(text("UPDATE tenant_features SET enabled = false WHERE tenant_id = :t AND feature = 'erp_hubsoft'"), {"t": seed["A"]})
    off = client.post(f"/v1/integrations/erp/{made['id']}/disable", headers=h).json()      # the kill switch works with the flag off
    assert (off["enabled"], off["status"]) == (False, "disabled")
    assert client.post(f"/v1/integrations/erp/{made['id']}/enable", headers=h).status_code == 403


def test_the_application_role_cannot_change_what_identifies_a_connection(client, seed, env, app_url):
    from sqlalchemy import create_engine
    made = create(client, hdr(client, "alice", seed, "A"))
    eng = create_engine(app_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed["A"])})
        for col, val in [("base_url", "'https://evil.example.com'"), ("secret_ref", "'other-ref'"), ("provider", "'ixc'")]:
            with pytest.raises(Exception, match="permission denied"):
                with c.begin_nested():
                    c.execute(text(f"UPDATE erp_connections SET {col} = {val} WHERE id = :i"), {"i": made["id"]})   # noqa: S608
        with pytest.raises(Exception, match="permission denied"):
            with c.begin_nested():
                c.execute(text("DELETE FROM erp_connections WHERE id = :i"), {"i": made["id"]})


def test_the_authentication_budget_is_shared_by_every_connection_and_worker(client, seed, env, monkeypatch, migrated):
    """The vendor's limit is per egress IP: two connections (and, by the same table, two processes) draw from ONE minute budget."""
    from app.main import app
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(update={"erp_secrets_dir": str(env), "erp_allowed_hosts": "erp.example.com", "erp_auth_per_minute": 2})
    h = hdr(client, "alice", seed, "A")
    one, two = create(client, h), create(client, h)
    _put_secret(env, seed["A"])
    net = net_for(monkeypatch, Net(tok(), tok(), tok()))
    first = client.post(f"/v1/integrations/erp/{one['id']}/test", headers=h).json()
    second = client.post(f"/v1/integrations/erp/{two['id']}/test", headers=h).json()
    third = client.post(f"/v1/integrations/erp/{one['id']}/test", headers=h).json()
    assert [first["status"], second["status"], third["status"]] == ["healthy", "healthy", "rate_limited"]
    assert third["last_error_class"] == "RATE_LIMITED" and len(net.calls) == 2      # the third was refused before anything was sent
    with migrated.begin() as c:
        assert c.execute(text("SELECT sum(n) FROM erp_egress_budget WHERE scope = 'hubsoft.auth'")).scalar() == 2


def test_concurrent_sends_never_pass_the_shared_budget(env, migrated):
    cap, passed, refused = 3, [], []

    def one():
        try:
            erp_connections._auth_gate(cap)()
            passed.append(1)
        except HubSoftError as e:
            assert e.code == "RATE_LIMITED" and 0 < e.retry_after <= 60
            refused.append(1)
    ts = [threading.Thread(target=one) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(passed) + len(refused) == 12 and len(passed) <= cap and len(passed) >= 1     # (a minute boundary during the run may open a second window: never more than one per window)


def test_every_authentication_send_counts_including_retries():
    spent = []
    net = Net(status(503), status(503), tok())
    c, _ = client(net, auth_gate=lambda: spent.append(1))
    c.token()
    assert len(spent) == 3 == len(net.calls)
    blocked = HubSoftClient(creds=Credentials("c", "s", "u", "p", "v"), key=("t", "c", "h", "v"), send=Net(tok()), cache=TokenCache(),
                            auth_gate=lambda: (_ for _ in ()).throw(HubSoftError("RATE_LIMITED", retry_after=30.0)))
    with pytest.raises(HubSoftError, match="RATE_LIMITED"):
        blocked.token()


def test_the_kill_switch_is_not_queued_behind_a_slow_test_and_the_test_cannot_undo_it(client, seed, env, monkeypatch):
    h = hdr(client, "alice", seed, "A")
    made = create(client, h)
    _put_secret(env, seed["A"])
    inside, release = threading.Event(), threading.Event()

    def slow(method, path, headers, body, params):
        inside.set()
        release.wait(10)
        return tok()
    monkeypatch.setattr(erp_connections, "_send_for", lambda host, addrs: slow)
    out = {}
    t = threading.Thread(target=lambda: out.update(r=client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h)))
    t.start()
    assert inside.wait(10)                     # the test is now "talking to the ERP"
    done = {}
    d = threading.Thread(target=lambda: done.update(r=client.post(f"/v1/integrations/erp/{made['id']}/disable", headers=h)))
    d.start()
    d.join(5)
    assert not d.is_alive() and done["r"].status_code == 200 and done["r"].json()["status"] == "disabled"     # not blocked by the test's transaction
    release.set()
    t.join(10)
    assert out["r"].status_code == 200 and out["r"].json()["status"] == "disabled"      # the late result did not bring it back
    assert client.post(f"/v1/integrations/erp/{made['id']}/test", headers=h).json()["detail"] == "connection_disabled"
