"""Webhooks de saída (ADR-0051 D2): segredo, assinatura, validação de URL e a entrega protegida contra SSRF.

* Segredo HMAC `whsec_<43>`: mostrado UMA vez; guardado CIFRADO (Fernet, `WEBHOOK_ENCRYPTION_KEY`); sem a chave os webhooks não existem (falha fechada).
* Assinatura: `X-FiberCore-Signature: t=<unix>,v1=<hex HMAC-SHA256(segredo, "<t>.<corpo>")>`; o receptor confere e recusa `t` antigo (anti-repetição).
* URL: só `https://`, host por NOME (nunca endereço IP literal), sem credencial na URL; na entrega TODO endereço resolvido tem de ser global (público): loopback, privado, link-local
  (inclui o serviço de metadados 169.254.169.254), CGNAT, multicast, reservado, ou IPv4 embutido em IPv6, derrubam a entrega. A conexão é feita ao IP JÁ VALIDADO (sem segunda
  resolução: sem DNS rebinding), com SNI e verificação de certificado pelo NOME; sem redirecionamento; tempo limite curto; resposta lida até 16 KB.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import Settings

EVENTS = ("incident.opened", "incident.resolved")     # keep in step with EVENTS in migration 0061 (a test compares the two)
MAX_ENDPOINTS = 10
MAX_BODY = 16 * 1024
TIMEOUT = 10.0
SIGNATURE_HEADER = "X-FiberCore-Signature"


class DeliveryError(Exception):
    """A delivery that did not succeed; `code` is a short, safe class name (never an address, a header or a body)."""

    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code, self.status = code, status


def available(settings: Settings) -> bool:
    return bool(settings.webhook_encryption_key)


def _fernet(settings: Settings) -> Fernet:
    if not settings.webhook_encryption_key:
        raise RuntimeError("webhooks are not configured")
    return Fernet(settings.webhook_encryption_key.encode())


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def encrypt_secret(settings: Settings, secret: str) -> str:
    return _fernet(settings).encrypt(secret.encode()).decode()


def decrypt_secret(settings: Settings, blob: str) -> str | None:
    try:
        return _fernet(settings).decrypt(blob.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def sign(secret: str, body: bytes, now: int | None = None) -> str:
    t = int(time.time()) if now is None else now
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, header: str, body: bytes, tolerance: int = 300, now: int | None = None) -> bool:
    """What a RECEIVER does (kept here so the documentation and the tests use the same code)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((int(time.time()) if now is None else now) - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))


def url_problem(url: str) -> str | None:
    """A stable code, or None. Syntax only (the database CHECK repeats the shape); the network rules apply at delivery."""
    if len(url) > 500:
        return "url_too_long"
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return "url_invalid"
    if u.scheme != "https":
        return "url_must_be_https"
    if not u.hostname or u.username or u.password or "@" in u.netloc:
        return "url_invalid"
    host = u.hostname
    try:
        ipaddress.ip_address(host)
        return "url_host_must_be_a_name"      # an IP literal is never accepted: no way to point at a private address by number
    except ValueError:
        pass
    if "." not in host or host.endswith(".") or host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal", ".localhost")):
        return "url_host_not_public"
    if port is not None and not 1 <= port <= 65535:
        return "url_invalid"
    if u.fragment:
        return "url_invalid"
    return None


def _ip_ok(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv6Address) and (ip.sixtofour is not None or ip.teredo is not None):
        return False
    return ip.is_global and not ip.is_multicast


def resolve_public(host: str, port: int, resolver: Callable = socket.getaddrinfo) -> list[str]:
    """Every address the name resolves to, all of which must be public. One non-public address refuses the delivery (a name that mixes public and private answers is hostile)."""
    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise DeliveryError("dns_failed") from exc
    addrs = []
    for info in infos:
        a = info[4][0].split("%")[0]
        if not _ip_ok(a):
            raise DeliveryError("address_not_public")
        if a not in addrs:
            addrs.append(a)
    if not addrs:
        raise DeliveryError("dns_failed")
    return addrs


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to an address ALREADY validated, with the certificate checked against the NAME (SNI + hostname verification)."""

    def __init__(self, host: str, port: int, ip: str, context: ssl.SSLContext, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def deliver(url: str, body: bytes, headers: dict[str, str], *, resolver: Callable = socket.getaddrinfo, context: ssl.SSLContext | None = None, allow_private: bool = False) -> int:
    """POST `body`. Returns the HTTP status when it is 2xx; raises `DeliveryError(code[, status])` otherwise. `allow_private` and `context` exist ONLY for the tests (a loopback server with its own CA)."""
    if len(body) > MAX_BODY:
        raise DeliveryError("body_too_large")
    problem = url_problem(url)
    if problem and not allow_private:
        raise DeliveryError(problem)
    u = urlsplit(url)
    host, port = u.hostname or "", u.port or 443
    if allow_private:
        ip = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4][0]
    else:
        ip = resolve_public(host, port, resolver)[0]
    ctx = context or ssl.create_default_context()
    conn = _PinnedHTTPSConnection(host, port, ip, ctx, TIMEOUT)
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    try:
        conn.request("POST", path, body=body, headers={"Host": host if not u.port else f"{host}:{port}", "Content-Length": str(len(body)), **headers})
        resp = conn.getresponse()
        resp.read(16 * 1024)        # never more than 16 KB of an answer
        status = resp.status
    except ssl.SSLError as exc:
        raise DeliveryError("tls_failed") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise DeliveryError("timeout") from exc
    except OSError as exc:
        raise DeliveryError("connection_failed") from exc
    finally:
        conn.close()
    if 200 <= status < 300:
        return status
    raise DeliveryError("redirect_not_followed" if 300 <= status < 400 else "http_error", status)


def build_request(settings: Settings, secret_enc: str, delivery_id, event_type: str, payload: dict) -> tuple[bytes, dict[str, str]]:
    secret = decrypt_secret(settings, secret_enc)
    if secret is None:
        raise DeliveryError("secret_unreadable")
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return body, {"Content-Type": "application/json", "User-Agent": "FiberCore-Webhook/1", "X-FiberCore-Event": event_type, "X-FiberCore-Delivery": str(delivery_id),
                  SIGNATURE_HEADER: sign(secret, body)}
