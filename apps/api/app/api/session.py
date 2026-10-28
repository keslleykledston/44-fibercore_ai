from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.routes import _client_ip, _gate, _record, _throttled
from app.core import mfa
from app.core.db import get_engine, scoped_connection
from app.core.security import decode_mfa_challenge, decode_token, verify_secret
from app.core.sessions import hash_refresh, issue_session
from app.core.settings import Settings, get_settings, required_mfa_roles

router = APIRouter()


def _unauth() -> HTTPException:
    return HTTPException(401, "invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"})


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class SessionOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


def _lock_family(conn, refresh_token: str) -> None:
    """Serialises refresh and logout on the same family, so a logout can never miss a successor created concurrently.
    READ COMMITTED: statements after the lock see everything committed before it was granted."""
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(f.family_id::text)) FROM "
             "(SELECT family_id FROM refresh_tokens WHERE token_hash = :h LIMIT 1) f"),
        {"h": hash_refresh(refresh_token)},
    )


def _revoke_family(conn, family_id: UUID) -> None:
    conn.execute(text("UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = :f AND revoked_at IS NULL"), {"f": family_id})


@router.post("/v1/auth/refresh", response_model=SessionOut)
def refresh(body: RefreshIn, settings: Settings = Depends(get_settings)) -> SessionOut:
    """Rotate: the presented token is consumed and a new one is issued in the same family. Presenting an already-consumed
    token means it leaked (or a client raced itself): the whole family is revoked and the user must log in again."""
    sess = None
    with scoped_connection(get_engine()) as conn:
        _lock_family(conn, body.refresh_token)
        row = conn.execute(
            text("SELECT id, family_id, user_id, expires_at, family_expires_at, used_at, grace_used_at, revoked_at FROM refresh_tokens "
                 "WHERE token_hash = :h FOR UPDATE"),
            {"h": hash_refresh(body.refresh_token)},
        ).first()
        now = datetime.now(UTC)
        if row is None or row.revoked_at is not None:
            pass  # unknown or revoked
        elif row.expires_at <= now or row.family_expires_at <= now:
            pass  # expired
        elif row.used_at is not None and (
            row.grace_used_at is not None or (now - row.used_at).total_seconds() > settings.refresh_reuse_grace_seconds
        ):
            # reuse: outside the grace window, or a second replay inside it (the one allowed sibling was already issued).
            # Treated as a leak. Revoked here; the 401 is raised after the transaction ends.
            _revoke_family(conn, row.family_id)
        elif not conn.execute(text("SELECT is_active FROM users_global WHERE id = :u"), {"u": row.user_id}).scalar():
            _revoke_family(conn, row.family_id)
        else:
            if row.used_at is None:
                conn.execute(text("UPDATE refresh_tokens SET used_at = now() WHERE id = :i"), {"i": row.id})
            else:  # a legitimate concurrent request (two tabs) within the grace window gets exactly one sibling; nothing is revoked
                conn.execute(text("UPDATE refresh_tokens SET grace_used_at = now() WHERE id = :i"), {"i": row.id})
            sess = issue_session(conn, settings, row.user_id, family_id=row.family_id, family_expires_at=row.family_expires_at)
    if sess is None:
        raise _unauth()
    return SessionOut(access_token=sess.access_token, refresh_token=sess.refresh_token, expires_in=sess.expires_in)


@router.post("/v1/auth/logout", status_code=204)
def logout(body: RefreshIn) -> Response:
    """Revokes the whole family. Idempotent and silent about unknown tokens."""
    with scoped_connection(get_engine()) as conn:
        _lock_family(conn, body.refresh_token)
        conn.execute(
            text("UPDATE refresh_tokens SET revoked_at = now() WHERE revoked_at IS NULL AND family_id IN "
                 "(SELECT family_id FROM refresh_tokens WHERE token_hash = :h)"),
            {"h": hash_refresh(body.refresh_token)},
        )
    return Response(status_code=204)


# ---- MFA: second step of login ---------------------------------------------------------------
class MfaVerifyIn(BaseModel):
    mfa_token: str = Field(min_length=10, max_length=2000)
    code: str = Field(min_length=6, max_length=32)  # 6-digit TOTP or a recovery code


def _check_second_factor(conn, settings: Settings, user_id: UUID, code: str) -> bool:
    """TOTP (replay-protected by time-step) or single-use recovery code. Runs inside the caller's throttled transaction."""
    row = conn.execute(text("SELECT secret_enc, last_step FROM user_mfa WHERE user_id = :u AND enabled"), {"u": user_id}).first()
    if row is None:
        return False
    secret = mfa.decrypt_secret(settings, row.secret_enc)
    if secret is None:
        return False
    if "-" not in code:
        step = mfa.verify_totp(secret, code, last_step=row.last_step)
        if step is None:
            return False
        return conn.execute(
            text("UPDATE user_mfa SET last_step = :s WHERE user_id = :u AND last_step < :s RETURNING 1"), {"s": step, "u": user_id}
        ).first() is not None
    return conn.execute(
        text("UPDATE mfa_recovery_codes SET used_at = now() WHERE user_id = :u AND code_hash = :h AND used_at IS NULL RETURNING 1"),
        {"u": user_id, "h": mfa.hash_recovery(code)},
    ).first() is not None


@router.post("/v1/auth/mfa/verify", response_model=SessionOut)
def mfa_verify(body: MfaVerifyIn, request: Request, settings: Settings = Depends(get_settings)) -> SessionOut:
    try:
        user_id = decode_mfa_challenge(settings, body.mfa_token)
    except (jwt.PyJWTError, ValueError) as exc:
        raise _unauth() from exc
    key, ip = f"mfa:{user_id}", _client_ip(request, settings)
    sess, outcome = None, "bad"
    with scoped_connection(get_engine()) as conn:
        if _gate(conn, key, ip):
            outcome = "locked"
        else:
            active = conn.execute(text("SELECT is_active FROM users_global WHERE id = :u"), {"u": user_id}).scalar()
            ok = bool(active) and _check_second_factor(conn, settings, user_id, body.code)
            _record(conn, key, ip, ok)
            if ok:
                sess, outcome = issue_session(conn, settings, user_id), "ok"
    if outcome == "locked":
        raise _throttled()
    if sess is None:
        raise HTTPException(401, "invalid credentials")
    return SessionOut(access_token=sess.access_token, refresh_token=sess.refresh_token, expires_in=sess.expires_in)


# ---- MFA: enrolment (authenticated user, re-authenticated with the password) -------------------
def _user_id(authorization: str | None, settings: Settings) -> UUID:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauth()
    try:
        claims = decode_token(settings, authorization[7:].strip())
    except (jwt.PyJWTError, ValueError) as exc:
        raise _unauth() from exc
    if claims.kind != "user":
        raise HTTPException(403, "users only")
    return claims.sub


def _reauth(conn, request: Request, settings: Settings, user_id: UUID, password: str):
    """Password re-check for sensitive MFA changes, throttled like a login. Returns the user's email."""
    key, ip = f"reauth:{user_id}", _client_ip(request, settings)
    if _gate(conn, key, ip):
        raise _throttled()
    row = conn.execute(text("SELECT email, password_hash, is_active FROM users_global WHERE id = :u"), {"u": user_id}).first()
    ok = bool(row and row.is_active) and verify_secret(row.password_hash if row else None, password)
    _record(conn, key, ip, ok)
    if not ok:
        return None
    return row.email


def _mfa_required(conn, settings: Settings, user_id: UUID) -> bool:
    roles = required_mfa_roles(settings)
    if not roles:
        return False
    mine = {r.role for r in conn.execute(text("SELECT role FROM tenant_memberships WHERE user_id = :u"), {"u": user_id})}
    return bool(roles & mine)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ActivateIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class DisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=32)


@router.get("/v1/auth/mfa/status")
def mfa_status(authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> dict:
    uid = _user_id(authorization, settings)
    with scoped_connection(get_engine(), user_id=uid) as conn:
        enabled = bool(conn.execute(text("SELECT enabled FROM user_mfa WHERE user_id = :u"), {"u": uid}).scalar())
        left = conn.execute(text("SELECT count(*) FROM mfa_recovery_codes WHERE user_id = :u AND used_at IS NULL"), {"u": uid}).scalar_one()
        required = _mfa_required(conn, settings, uid)
    return {"enabled": enabled, "recovery_codes_left": left, "enrolment_available": bool(settings.mfa_encryption_key),
            "required": required}


@router.post("/v1/auth/mfa/enroll")
def mfa_enroll(
    body: PasswordIn, request: Request, authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> dict:
    uid = _user_id(authorization, settings)
    if not settings.mfa_encryption_key:
        raise HTTPException(503, "MFA enrolment is not configured")  # fail closed: never store a secret unencrypted
    with scoped_connection(get_engine(), user_id=uid) as conn:
        email = _reauth(conn, request, settings, uid, body.password)
        if email is None:
            outcome = "bad"
        elif conn.execute(text("SELECT enabled FROM user_mfa WHERE user_id = :u"), {"u": uid}).scalar():
            outcome = "enabled"
        else:
            secret = mfa.new_secret()
            conn.execute(
                text("INSERT INTO user_mfa (user_id, secret_enc) VALUES (:u, :s) "
                     "ON CONFLICT (user_id) DO UPDATE SET secret_enc = EXCLUDED.secret_enc, last_step = 0, enabled = false"),
                {"u": uid, "s": mfa.encrypt_secret(settings, secret)},
            )
            outcome = "ok"
    if outcome == "bad":
        raise HTTPException(401, "invalid credentials")
    if outcome == "enabled":
        raise HTTPException(409, "MFA already enabled; disable it first")
    return {"secret": secret, "otpauth_uri": mfa.provisioning_uri(settings, email, secret)}


@router.post("/v1/auth/mfa/activate")
def mfa_activate(
    body: ActivateIn, request: Request, authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> dict:
    uid = _user_id(authorization, settings)
    key, ip = f"mfa:{uid}", _client_ip(request, settings)
    codes: list[str] = []
    with scoped_connection(get_engine(), user_id=uid) as conn:
        if _gate(conn, key, ip):
            outcome = "locked"
        else:
            row = conn.execute(text("SELECT secret_enc, last_step, enabled FROM user_mfa WHERE user_id = :u"), {"u": uid}).first()
            secret = mfa.decrypt_secret(settings, row.secret_enc) if row and not row.enabled else None
            step = mfa.verify_totp(secret, body.code, last_step=row.last_step) if secret else None
            _record(conn, key, ip, step is not None)
            if step is None:
                outcome = "bad"
            else:
                codes = mfa.new_recovery_codes()
                conn.execute(
                    text("UPDATE user_mfa SET enabled = true, enabled_at = now(), last_step = :s WHERE user_id = :u"), {"s": step, "u": uid}
                )
                conn.execute(text("DELETE FROM mfa_recovery_codes WHERE user_id = :u"), {"u": uid})
                for c in codes:
                    conn.execute(
                        text("INSERT INTO mfa_recovery_codes (user_id, code_hash) VALUES (:u, :h)"), {"u": uid, "h": mfa.hash_recovery(c)}
                    )
                outcome = "ok"
    if outcome == "locked":
        raise _throttled()
    if outcome == "bad":
        raise HTTPException(401, "invalid code")
    return {"enabled": True, "recovery_codes": codes}  # shown once; only hashes are stored


@router.post("/v1/auth/mfa/disable", status_code=204)
def mfa_disable(
    body: DisableIn, request: Request, authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> Response:
    uid = _user_id(authorization, settings)
    key, ip = f"mfa:{uid}", _client_ip(request, settings)
    with scoped_connection(get_engine(), user_id=uid) as conn:
        if _mfa_required(conn, settings, uid):  # required by policy: switching it off would lock the account out of every route
            raise HTTPException(409, "MFA is required for your role and cannot be disabled")
        if _gate(conn, key, ip):
            outcome = "locked"
        elif _reauth(conn, request, settings, uid, body.password) is None:
            outcome = "bad"
        else:
            ok = _check_second_factor(conn, settings, uid, body.code)
            _record(conn, key, ip, ok)
            outcome = "ok" if ok else "bad"
            if ok:
                conn.execute(text("DELETE FROM user_mfa WHERE user_id = :u"), {"u": uid})
                conn.execute(text("DELETE FROM mfa_recovery_codes WHERE user_id = :u"), {"u": uid})
    if outcome == "locked":
        raise _throttled()
    if outcome == "bad":
        raise HTTPException(401, "invalid credentials")
    return Response(status_code=204)
