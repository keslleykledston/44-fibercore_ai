from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.settings import Settings

_hasher = PasswordHasher()
# Verified against when the account does not exist, to keep timing uniform.
_DUMMY_HASH = _hasher.hash("fibercore-dummy-password")

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "isp_admin": frozenset({
        "customers:read", "customers:import", "associations:review", "incidents:read", "incidents:ack",
        "jobs:read", "jobs:request", "jobs:approve", "inventory:read", "tenant:read", "audit:read", "members:read", "edge:read",
        "members:mfa_reset", "diagnostics:run",
    }),
    "engineer": frozenset({
        "customers:read", "associations:review", "incidents:read", "incidents:ack", "jobs:read", "jobs:request",
        "inventory:read", "tenant:read", "edge:read", "diagnostics:run",
    }),
    "noc_n2": frozenset({
        "customers:read", "incidents:read", "incidents:ack", "jobs:read", "jobs:request", "inventory:read", "tenant:read", "edge:read",
        "diagnostics:run",
    }),
    "noc_n1": frozenset({"tenant:read", "inventory:read", "incidents:read"}),
    "support": frozenset({"tenant:read", "inventory:read", "customers:read"}),
    "auditor": frozenset({"tenant:read", "audit:read"}),
    "platform_support": frozenset({"tenant:read"}),  # only via delegated membership
    "edge_agent": frozenset({"edge:heartbeat", "inventory:write", "jobs:execute"}),  # service accounts of Edge agents: nothing else
}


def hash_secret(secret: str) -> str:
    return _hasher.hash(secret)


def verify_secret(stored_hash: str | None, secret: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, secret) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class TokenClaims:
    sub: UUID
    kind: str  # "user" | "service"
    tenant_id: UUID | None  # set only for service accounts
    iat: float = 0.0  # issue time (epoch s, fractional): compared with users_global.tokens_valid_after to honour revocations


def issue_token(settings: Settings, *, sub: UUID, kind: str, tenant_id: UUID | None = None) -> str:
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET not configured")
    now = time.time()  # fractional: revocation (users_global.tokens_valid_after) is compared at sub-second precision
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(sub),
        "kind": kind,
        "iat": now,
        "exp": int(now) + settings.jwt_ttl_seconds,
    }
    if tenant_id:
        claims["tid"] = str(tenant_id)
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256", headers={"kid": settings.jwt_kid})


def _verification_keys(settings: Settings, token: str) -> list[str]:
    """Candidate keys chosen by the (unverified) kid header; the signature check afterwards is what authenticates. A token
    without kid (issued before key rotation existed) is tried against the current key, then the previous one, so rotation
    does not cut legacy sessions short. An unknown kid never falls back."""
    previous = settings.jwt_secret_previous
    kid = jwt.get_unverified_header(token).get("kid")
    if kid is None:
        return [settings.jwt_secret] + ([previous] if previous else [])
    if kid == settings.jwt_kid:
        return [settings.jwt_secret]
    if previous and settings.jwt_kid_previous and kid == settings.jwt_kid_previous:
        return [previous]
    raise ValueError("unknown kid")


def _decode(settings: Settings, token: str, *, audience: str) -> dict:
    last: Exception = ValueError("no key")
    for key in _verification_keys(settings, token):
        try:
            return jwt.decode(token, key, algorithms=["HS256"], audience=audience, issuer=settings.jwt_issuer,
                              options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        except jwt.InvalidSignatureError as exc:
            last = exc  # try the next candidate key; every other failure (expired, audience...) is final
    raise last


CHALLENGE_TTL_SECONDS = 300


def issue_mfa_challenge(settings: Settings, *, sub: UUID) -> str:
    """Short-lived proof that the password step succeeded. Distinct audience: it can never be used as an access token."""
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET not configured")
    now = int(time.time())
    claims = {"iss": settings.jwt_issuer, "aud": f"{settings.jwt_audience}:mfa", "sub": str(sub), "kind": "mfa", "iat": now,
              "exp": now + CHALLENGE_TTL_SECONDS}
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256", headers={"kid": settings.jwt_kid})


def decode_mfa_challenge(settings: Settings, token: str) -> UUID:
    if not settings.jwt_secret:
        raise ValueError("auth not configured")
    data = _decode(settings, token, audience=f"{settings.jwt_audience}:mfa")
    if data.get("kind") != "mfa":
        raise ValueError("bad kind")
    return UUID(data["sub"])


def decode_token(settings: Settings, token: str) -> TokenClaims:
    """Raises jwt.PyJWTError / ValueError on any problem. Algorithm is pinned (no alg=none)."""
    if not settings.jwt_secret:
        raise ValueError("auth not configured")
    data = _decode(settings, token, audience=settings.jwt_audience)
    kind = data.get("kind")
    if kind not in ("user", "service"):
        raise ValueError("bad kind")
    tid = UUID(data["tid"]) if data.get("tid") else None
    if kind == "service" and tid is None:
        raise ValueError("service token without tenant")
    return TokenClaims(sub=UUID(data["sub"]), kind=kind, tenant_id=tid, iat=float(data["iat"]))
