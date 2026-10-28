from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import Settings

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # accept the previous/next step to tolerate clock drift
RECOVERY_CODES = 8


def new_secret() -> str:
    """160-bit secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()  # noqa: S324 - RFC 4226/6238 mandate HMAC-SHA1
    off = digest[-1] & 0x0F
    return str((struct.unpack(">I", digest[off : off + 4])[0] & 0x7FFFFFFF) % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify_totp(secret_b32: str, code: str, *, last_step: int, now: float | None = None) -> int | None:
    """Returns the matched time-step (to be persisted as the new last_step) or None. A step <= last_step is a replay."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    base = current_step(now)
    matched: int | None = None
    for step in range(base - WINDOW, base + WINDOW + 1):  # constant work: no early exit on the first hit
        if hmac.compare_digest(_hotp(secret_b32, step), code) and step > last_step:
            matched = step if matched is None else max(matched, step)
    return matched


def provisioning_uri(settings: Settings, email: str, secret_b32: str) -> str:
    label = quote(f"{settings.mfa_issuer}:{email}")
    return f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(settings.mfa_issuer)}&digits={DIGITS}&period={STEP_SECONDS}"


def _fernet(settings: Settings) -> Fernet:
    if not settings.mfa_encryption_key:
        raise RuntimeError("MFA_ENCRYPTION_KEY not configured")
    return Fernet(settings.mfa_encryption_key.encode())


def encrypt_secret(settings: Settings, secret_b32: str) -> bytes:
    return _fernet(settings).encrypt(secret_b32.encode())


def decrypt_secret(settings: Settings, blob: bytes) -> str | None:
    try:
        return _fernet(settings).decrypt(bytes(blob)).decode()
    except InvalidToken:
        return None


def new_recovery_codes() -> list[str]:
    return [f"{secrets.token_hex(5)}-{secrets.token_hex(5)}" for _ in range(RECOVERY_CODES)]  # 80 random bits each


def hash_recovery(code: str) -> bytes:
    # 80 random bits: a fast hash is adequate; offline guessing after a leak is infeasible at this entropy.
    return hashlib.sha256(code.strip().lower().encode()).digest()
