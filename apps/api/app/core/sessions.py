from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.core.security import issue_token
from app.core.settings import Settings


def hash_refresh(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


@dataclass(frozen=True)
class Session:
    access_token: str
    refresh_token: str
    expires_in: int


def issue_session(
    conn: Connection, settings: Settings, user_id: UUID, *, family_id: UUID | None = None, family_expires_at: datetime | None = None,
    mfa_at: datetime | None = None,
) -> Session:
    """New access token + opaque refresh token. A refresh token belongs to a family; the family has an absolute expiry that
    rotation never extends, so a stolen cookie cannot be kept alive forever. `mfa_at` is when this family last proved a second factor: a login
    with MFA sets it, a refresh carries it unchanged, only a step-up renews it (ADR-0031, "MFA recente")."""
    now = datetime.now(UTC)
    family_id = family_id or uuid4()
    family_expires_at = family_expires_at or now + timedelta(seconds=settings.refresh_family_ttl_seconds)
    expires_at = min(now + timedelta(seconds=settings.refresh_ttl_seconds), family_expires_at)
    refresh = secrets.token_urlsafe(32)
    conn.execute(
        text(
            "INSERT INTO refresh_tokens (family_id, user_id, token_hash, expires_at, family_expires_at, mfa_at) "
            "VALUES (:f, :u, :h, :e, :fe, :m)"
        ),
        {"f": family_id, "u": user_id, "h": hash_refresh(refresh), "e": expires_at, "fe": family_expires_at, "m": mfa_at},
    )
    # opportunistic, bounded retention of long-dead rows (kept a week past expiry for reuse detection)
    conn.execute(
        text("DELETE FROM refresh_tokens WHERE id IN "
             "(SELECT id FROM refresh_tokens WHERE family_expires_at < now() - interval '7 days' LIMIT 200)")
    )
    return Session(issue_token(settings, sub=user_id, kind="user", mfa_at=mfa_at.timestamp() if mfa_at else None), refresh, settings.jwt_ttl_seconds)


def mfa_enabled(conn: Connection, user_id: UUID) -> bool:
    return bool(conn.execute(text("SELECT enabled FROM user_mfa WHERE user_id = :u"), {"u": user_id}).scalar())
