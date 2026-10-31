"""HubSoft, READ-ONLY (ADR-0033): the OAuth password-grant token with its cache, and an authorised GET with the failure policy of the homologation plan.

What is documented by the vendor and used here: `POST /oauth/token` (client_id, client_secret, username, password, grant_type=password) answering an
`access_token` and `expires_in`; `Authorization: Bearer`; HTTP 401/403/429. Nothing else is assumed (no route syntax, no search types). This is NOT a
homologated integration: it has only been exercised against mocks until an authorised instance says otherwise.

Policy: the token is cached per (tenant, connection, host, credential version) until shortly before it expires and never fetched per query; 401 on a request drops
the token and authenticates ONCE more; 403 is final; 429 waits the vendor's `retry_after` only when it is short, otherwise it is reported; 5xx/timeouts are retried
a bounded number of times with jitter; redirects are refused. Our own limiters stay well under the published limits (per IP: auth 30/min, other 20/s).
No secret, token or response body is ever logged or put in an error."""
from __future__ import annotations

import json
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.erp_hub import Credentials

MAX_BODY = 1 << 20
TOKEN_PATH = "/oauth/token"  # noqa: S105  (a URL path, not a password)
INVALID_AUTH, FORBIDDEN, RATE_LIMITED, BAD_REQUEST, TEMPORARILY_UNAVAILABLE, BAD_RESPONSE = (
    "INVALID_AUTH", "FORBIDDEN", "RATE_LIMITED", "BAD_REQUEST", "TEMPORARILY_UNAVAILABLE", "BAD_RESPONSE")
_STATE_OF = {INVALID_AUTH: "unauthorized", FORBIDDEN: "unauthorized", RATE_LIMITED: "rate_limited", TEMPORARILY_UNAVAILABLE: "offline", BAD_RESPONSE: "degraded", BAD_REQUEST: "degraded"}


class HubSoftError(Exception):
    def __init__(self, code: str, *, retry_after: float | None = None, status: int | None = None):
        super().__init__(code)
        self.code, self.retry_after, self.status = code, retry_after, status

    @property
    def state(self) -> str:
        return _STATE_OF.get(self.code, "degraded")


@dataclass(frozen=True)
class Raw:
    status: int
    headers: dict[str, str]
    body: bytes


Send = Callable[[str, str, dict[str, str], Any, dict[str, str] | None], Raw]   # method, path, headers, json body, query params


def make_send(host: str, addresses: list[str], transport: httpx.BaseTransport | None = None, connect_timeout: float = 5.0, read_timeout: float = 10.0) -> Send:
    """Sends to an ADDRESS that was checked as public (connect by IP, SNI and Host by name, so TLS still verifies the name); redirects are never followed."""
    def send(method: str, path: str, headers: dict[str, str], body: Any, params: dict[str, str] | None) -> Raw:
        last: Exception | None = None
        for ip in addresses:
            netloc = f"[{ip}]" if ":" in ip else ip
            try:
                with httpx.Client(transport=transport, follow_redirects=False, timeout=httpx.Timeout(read_timeout, connect=connect_timeout), verify=True, trust_env=False) as c:
                    with c.stream(method, f"https://{netloc}{path}", headers={**headers, "Host": host}, json=body, params=params, extensions={"sni_hostname": host}) as r:
                        buf = b""
                        for chunk in r.iter_bytes():
                            buf += chunk
                            if len(buf) > MAX_BODY:
                                raise HubSoftError(BAD_RESPONSE)
                        return Raw(r.status_code, {k.lower(): v for k, v in r.headers.items()}, buf)
            except HubSoftError:
                raise
            except httpx.HTTPError as e:   # connect/read/timeout: try the next address, then give up as unavailable
                last = e
        raise HubSoftError(TEMPORARILY_UNAVAILABLE) from last
    return send


class TokenCache:
    def __init__(self) -> None:
        self._d: dict[tuple, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._key_locks: dict[tuple, threading.Lock] = {}

    def get(self, key: tuple, now: float) -> str | None:
        with self._lock:
            hit = self._d.get(key)
            return hit[0] if hit and now < hit[1] else None

    def put(self, key: tuple, token: str, valid_until: float) -> None:
        with self._lock:
            self._d[key] = (token, valid_until)

    def drop(self, key: tuple) -> None:
        with self._lock:
            self._d.pop(key, None)

    def lock_for(self, key: tuple) -> threading.Lock:
        with self._lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


CACHE = TokenCache()


class RateLimiter:
    """Token bucket per connection; `take()` is how long the caller must wait (0 = go)."""

    def __init__(self, per_second: float, burst: int, clock: Callable[[], float] = time.monotonic):
        self.rate, self.burst, self.clock = per_second, float(burst), clock
        self.tokens, self.at, self._lock = float(burst), clock(), threading.Lock()

    def take(self) -> float:
        with self._lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
            self.at = now
            if self.tokens >= 1:
                self.tokens -= 1
                return 0.0
            return (1 - self.tokens) / self.rate


@dataclass
class Policy:
    request_per_second: float = 2.0     # conservative for the first homologation (documented limit: 20/s per IP, shared)
    request_burst: int = 4
    auth_per_minute: float = 6.0        # documented limit: 30/min per IP, shared
    auth_burst: int = 3                 # room for the first try and the two bounded retries of a flaky answer
    max_retry_after: float = 5.0        # a longer wait is reported (RATE_LIMITED) instead of holding a request open
    max_5xx_retries: int = 2
    deadline: float = 20.0
    skew: float = 30.0


@dataclass
class HubSoftClient:
    creds: Credentials = field(repr=False)
    key: tuple                                   # (tenant_id, connection_id, host, credential version)
    send: Send
    policy: Policy = field(default_factory=Policy)
    cache: TokenCache = CACHE
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    rng: Callable[[], float] = random.random
    limiter: RateLimiter | None = None
    auth_limiter: RateLimiter | None = None
    auth_calls: int = 0

    def __post_init__(self) -> None:
        self.limiter = self.limiter or RateLimiter(self.policy.request_per_second, self.policy.request_burst, self.clock)
        self.auth_limiter = self.auth_limiter or RateLimiter(self.policy.auth_per_minute / 60.0, self.policy.auth_burst, self.clock)

    # --- one HTTP exchange with the failure policy -----------------------------------------------------
    def _retry_after(self, raw: Raw) -> float | None:
        v = raw.headers.get("retry-after")
        if v is not None:
            try:
                return max(0.0, float(v))
            except ValueError:
                pass
        try:
            body = json.loads(raw.body or b"{}")
            ra = body.get("retry_after") if isinstance(body, dict) else None
            return max(0.0, float(ra)) if isinstance(ra, (int, float)) and not isinstance(ra, bool) else None
        except ValueError:
            return None

    def _call(self, limiter: RateLimiter, do: Callable[[], Raw], started: float) -> Raw:
        """Runs `do` until it gets a non-retryable answer. 429 waits only a short retry_after (once); 5xx/transport errors back off with jitter."""
        retries_5xx = 0
        waited_429 = False
        while True:
            wait = limiter.take()
            while wait > 0:
                if wait > self.policy.max_retry_after:
                    raise HubSoftError(RATE_LIMITED, retry_after=wait)   # our own limiter: never queue a request behind a long wait
                self.sleep(wait)
                wait = limiter.take()   # the token we waited for must be taken, or the next caller gets it for free
            if self.clock() - started > self.policy.deadline:
                raise HubSoftError(TEMPORARILY_UNAVAILABLE)
            try:
                raw = do()
            except HubSoftError as e:
                if e.code != TEMPORARILY_UNAVAILABLE or retries_5xx >= self.policy.max_5xx_retries:
                    raise
                retries_5xx += 1
                self.sleep(min(2.0, 0.25 * 2 ** retries_5xx) * (0.5 + self.rng()))
                continue
            if raw.status == 429:
                ra = self._retry_after(raw)
                if waited_429 or ra is None or ra > self.policy.max_retry_after:
                    raise HubSoftError(RATE_LIMITED, retry_after=ra, status=429)
                waited_429 = True
                self.sleep(ra + 0.1 * self.rng())
                continue
            if raw.status >= 500:
                if retries_5xx >= self.policy.max_5xx_retries:
                    raise HubSoftError(TEMPORARILY_UNAVAILABLE, status=raw.status)
                retries_5xx += 1
                self.sleep(min(2.0, 0.25 * 2 ** retries_5xx) * (0.5 + self.rng()))
                continue
            return raw

    # --- token ----------------------------------------------------------------------------------------
    def _authenticate(self, started: float) -> str:
        self.auth_calls += 1
        body = {"client_id": self.creds.client_id, "client_secret": self.creds.client_secret, "username": self.creds.username,
                "password": self.creds.password, "grant_type": "password"}
        raw = self._call(self.auth_limiter, lambda: self.send("POST", TOKEN_PATH, {"Accept": "application/json"}, body, None), started)
        if raw.status in (301, 302, 303, 307, 308):
            raise HubSoftError(BAD_RESPONSE, status=raw.status)   # a redirect would carry the credentials somewhere we did not vet
        if raw.status == 401:
            raise HubSoftError(INVALID_AUTH, status=401)
        if raw.status == 403:
            raise HubSoftError(FORBIDDEN, status=403)
        try:
            data = json.loads(raw.body)
        except ValueError:
            data = None
        if raw.status == 400:
            err = data.get("error") if isinstance(data, dict) else None
            raise HubSoftError(INVALID_AUTH if err in ("invalid_grant", "invalid_client", "unauthorized_client") else BAD_REQUEST, status=400)
        if raw.status != 200 or not isinstance(data, dict):
            raise HubSoftError(BAD_RESPONSE, status=raw.status)
        tok, ttl = data.get("access_token"), data.get("expires_in")
        if not isinstance(tok, str) or not 8 <= len(tok) <= 4096 or isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not 1 <= ttl <= 31 * 86400:
            raise HubSoftError(BAD_RESPONSE, status=200)
        margin = min(self.policy.skew, ttl / 2)   # refresh a little early; a very short token is used for what it is worth
        self.cache.put(self.key, tok, self.clock() + ttl - margin)
        return tok

    def token(self, started: float | None = None) -> str:
        started = self.clock() if started is None else started
        with self.cache.lock_for(self.key):   # concurrent callers of one connection share one authentication
            hit = self.cache.get(self.key, self.clock())
            return hit if hit is not None else self._authenticate(started)

    # --- an authorised GET (HS-03 builds on this) ---------------------------------------------------
    def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        started = self.clock()
        for attempt in (1, 2):
            tok = self.token(started)
            raw = self._call(self.limiter, lambda tok=tok: self.send("GET", path, {"Authorization": f"Bearer {tok}", "Accept": "application/json"}, None, params), started)
            if raw.status == 401 and attempt == 1:
                self.cache.drop(self.key)   # the token may have been revoked or expired early: authenticate ONCE more
                continue
            if raw.status == 401:
                raise HubSoftError(INVALID_AUTH, status=401)
            if raw.status == 403:
                raise HubSoftError(FORBIDDEN, status=403)
            if raw.status in (301, 302, 303, 307, 308):
                raise HubSoftError(BAD_RESPONSE, status=raw.status)
            if raw.status == 404:
                raise HubSoftError("NOT_FOUND", status=404)
            if raw.status >= 400:
                raise HubSoftError(BAD_REQUEST, status=raw.status)
            try:
                return json.loads(raw.body)
            except ValueError:
                raise HubSoftError(BAD_RESPONSE, status=raw.status) from None
        raise HubSoftError(INVALID_AUTH)   # unreachable: the loop returns or raises


def test_connection(client: HubSoftClient) -> None:
    """The minimal authorised check of HS-02: obtaining a token (the cache is bypassed so the CREDENTIALS are what is tested). Nothing else is called."""
    client.cache.drop(client.key)
    client.token()
