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
        "inventory:read", "tenant:read", "audit:read", "members:read", "edge:read",
    }),
    "engineer": frozenset({
        "customers:read", "associations:review", "incidents:read", "incidents:ack", "inventory:read", "tenant:read", "edge:read",
    }),
    "noc_n2": frozenset({"customers:read", "incidents:read", "incidents:ack", "inventory:read", "tenant:read", "edge:read"}),
    "noc_n1": frozenset({"tenant:read", "inventory:read", "incidents:read"}),
    "support": frozenset({"tenant:read", "inventory:read", "customers:read"}),
    "auditor": frozenset({"tenant:read", "audit:read"}),
    "platform_support": frozenset({"tenant:read"}),  # only via delegated membership
    "edge_agent": frozenset({"edge:heartbeat", "inventory:write"}),  # service accounts of Edge agents: nothing else
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


def issue_token(settings: Settings, *, sub: UUID, kind: str, tenant_id: UUID | None = None) -> str:
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET not configured")
    now = int(time.time())
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(sub),
        "kind": kind,
        "iat": now,
        "exp": now + settings.jwt_ttl_seconds,
    }
    if tenant_id:
        claims["tid"] = str(tenant_id)
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_token(settings: Settings, token: str) -> TokenClaims:
    """Raises jwt.PyJWTError / ValueError on any problem. Algorithm is pinned (no alg=none)."""
    if not settings.jwt_secret:
        raise ValueError("auth not configured")
    data = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
    )
    kind = data.get("kind")
    if kind not in ("user", "service"):
        raise ValueError("bad kind")
    tid = UUID(data["tid"]) if data.get("tid") else None
    if kind == "service" and tid is None:
        raise ValueError("service token without tenant")
    return TokenClaims(sub=UUID(data["sub"]), kind=kind, tenant_id=tid)
