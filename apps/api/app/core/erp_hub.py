"""ERP Integration Hub, the vendor-agnostic part (ADR-0033): the provider registry, what a connection may say, and where its secret lives.

HubSoft is the FIRST ERP to be homologated (P0); IXC (P1) and SGP (P2) stay in the registry, disabled, with no real connector. A connection stores a
`secret_ref`, never a secret: the credentials are a file the operator places on the server (`ERP_SECRETS_DIR/<tenant_id>/<ref>.json`, mode 0600), so a tenant
can only ever name its own directory. Nothing here makes a network call."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    priority: str
    auth_profiles: tuple[str, ...]
    sync_modes: tuple[str, ...]
    real_connector: bool          # False = contracts and mocks only; a connection of this provider cannot be created, tested or enabled
    integration_status: str       # never "homologated" in code: homologation is a fact recorded after a real, authorised test


PROVIDERS: dict[str, Provider] = {
    "hubsoft": Provider("hubsoft", "HubSoft", "P0", ("hubsoft_oauth_credentials",), ("lookup_only",), True, "planned_unverified"),
    "ixc": Provider("ixc", "IXC Provedor", "P1", ("ixc_user_api_token",), ("lookup_only",), False, "deferred_not_homologated"),
    "sgp": Provider("sgp", "SGP/TSMX", "P2", ("sgp_legacy_token_app_body", "sgp_v1_bearer_explicit"), ("lookup_only",), False, "deferred_not_homologated"),
}
HOMOLOGATION_ORDER = ("hubsoft", "ixc", "sgp")
STATES = ("unconfigured", "validating", "healthy", "degraded", "unauthorized", "rate_limited", "offline", "disabled")

REF_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class ConnectionInvalid(ValueError):
    """The code is the message: a short, stable token the API returns (never an echo of what was submitted)."""


def parse_allowed_hosts(raw: str) -> tuple[str, ...]:
    return tuple(sorted({h.strip().lower() for h in raw.split(",") if h.strip()}))


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    """Exact host, or `*.suffix` for any label(s) below it. An empty list allows nothing (fail closed)."""
    for rule in allowed:
        if rule.startswith("*."):
            if host.endswith(rule[1:]) and host != rule[2:]:
                return True
        elif host == rule:
            return True
    return False


def normalize_base_url(raw: str, allowed: tuple[str, ...]) -> str:
    """https only, a DNS name (no IP literal), default port, no credentials/path/query, and on the operator's allowlist. Returns `https://host`."""
    if not isinstance(raw, str) or len(raw) > 300 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in raw):
        raise ConnectionInvalid("base_url_invalid")
    u = urlsplit(raw)
    try:
        port = u.port
    except ValueError:
        raise ConnectionInvalid("base_url_invalid") from None
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.username is not None or u.password is not None or u.query or u.fragment or u.path not in ("", "/") or port not in (None, 443):
        raise ConnectionInvalid("base_url_invalid")
    if not HOST_RE.match(host):
        raise ConnectionInvalid("base_url_invalid")   # also rejects IP literals, 'localhost' and single-label names
    if not host_allowed(host, allowed):
        raise ConnectionInvalid("base_url_not_allowed")
    return f"https://{host}"


def validate_connection(provider: str, auth_profile: str, transport_mode: str, sync_mode: str, secret_ref: str) -> Provider:
    p = PROVIDERS.get(provider)
    if p is None:
        raise ConnectionInvalid("unknown_provider")
    if not p.real_connector:
        raise ConnectionInvalid("provider_not_available")   # IXC and SGP: contracts and mocks only, until HubSoft is homologated
    if auth_profile not in p.auth_profiles:
        raise ConnectionInvalid("auth_profile_not_supported")
    if transport_mode != "cloud":
        raise ConnectionInvalid("transport_not_available")   # Edge transport for a private ERP comes with its own delivery
    if sync_mode not in p.sync_modes:
        raise ConnectionInvalid("sync_mode_not_supported")   # lookup_only until a paginated/incremental listing is proven on an authorised instance
    if not isinstance(secret_ref, str) or not REF_RE.match(secret_ref):
        raise ConnectionInvalid("secret_ref_invalid")
    return p


Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


def resolve_public(host: str, resolver: Resolver = system_resolver) -> list[str]:
    """Every address the name resolves to must be a public one; ONE private/loopback/link-local/reserved answer refuses the whole name (rebinding to an
    internal host is the attack). The caller connects to the returned address, not to the name, so the check and the use see the same address."""
    try:
        addrs = resolver(host)
    except OSError:
        raise ConnectionInvalid("host_unresolvable") from None
    if not addrs:
        raise ConnectionInvalid("host_unresolvable")
    out: list[str] = []
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            raise ConnectionInvalid("host_not_public") from None
        if not ip.is_global or ip.is_multicast:
            raise ConnectionInvalid("host_not_public")
        out.append(str(ip))
    return out


class SecretError(Exception):
    """A stable code (secret_not_found, secret_permissions, secret_invalid); never a value, never a path."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Credentials:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    version: str = ""     # hash of the secret file: a rotated secret is a new cache key


_FIELDS = ("client_id", "client_secret", "username", "password")


def load_credentials(secrets_dir: str, tenant_id: UUID, ref: str) -> Credentials:
    """`<secrets_dir>/<tenant_id>/<ref>.json` with exactly the four fields, owned by the service and not readable by group/others."""
    if not secrets_dir or not REF_RE.match(ref):
        raise SecretError("secret_not_found")
    base = Path(secrets_dir)
    path = base / str(tenant_id) / f"{ref}.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)   # a symlink in place of the file is refused
    except OSError:
        raise SecretError("secret_not_found") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_size > 8192:
            raise SecretError("secret_permissions")
        raw = os.read(fd, 8193)
    finally:
        os.close(fd)
    try:
        data = json.loads(raw)
    except ValueError:
        raise SecretError("secret_invalid") from None
    if not isinstance(data, dict) or set(data) != set(_FIELDS) or any(not isinstance(data[k], str) or not 1 <= len(data[k]) <= 512 for k in _FIELDS):
        raise SecretError("secret_invalid")
    return Credentials(**{k: data[k] for k in _FIELDS}, version=hashlib.sha256(raw).hexdigest()[:16])
