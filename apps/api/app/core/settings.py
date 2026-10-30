from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Secrets come from env or *_FILE (Docker secrets), never from Git."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    environment: str = "dev"
    # Runtime role: non-owner, NO BYPASSRLS. Migrations use ADMIN_DATABASE_URL instead.
    database_url: str = ""
    module_manifest: Path = Path("/app/configs/modules.yaml")
    nats_monitor_url: str = ""
    jwt_secret: str = Field(default="", repr=False)
    jwt_issuer: str = "fibercore-api"
    jwt_audience: str = "fibercore"
    jwt_ttl_seconds: int = 900
    # Key ring: new tokens are signed with jwt_secret/jwt_kid; tokens signed with the previous key stay valid until they expire.
    jwt_kid: str = "k1"
    jwt_secret_previous: str = Field(default="", repr=False)
    jwt_kid_previous: str = ""
    refresh_ttl_seconds: int = 8 * 3600  # sliding: each rotation issues a fresh window
    refresh_family_ttl_seconds: int = 7 * 24 * 3600  # absolute cap: re-login required after this
    # A refresh token presented again within this window (a legitimate concurrent request, e.g. two tabs) gets a sibling token
    # instead of revoking the family; outside it, reuse is treated as a leak.
    refresh_reuse_grace_seconds: int = 10
    mfa_encryption_key: str = Field(default="", repr=False)  # Fernet key (urlsafe base64, 32 bytes); empty => MFA enrolment disabled
    mfa_issuer: str = "FiberCore"
    # Comma-separated tenant roles that MUST have MFA enabled (e.g. "isp_admin"). A user with such a role in ANY tenant gets
    # 403 mfa_enrolment_required on every tenant-scoped route until MFA is on, and cannot switch it off. Empty = policy off.
    mfa_required_roles: str = ""
    trusted_proxy: bool = False  # trust X-Forwarded-For (set only behind our own reverse proxy)
    job_signing_key: str = Field(default="", repr=False)  # base64 Ed25519 seed; empty => dispatch disabled (fail closed)
    pii_hmac_key: str = Field(default="", repr=False)  # HMAC key for customer documents; import fails closed without it

    @field_validator("jwt_secret", "jwt_secret_previous", "pii_hmac_key")
    @classmethod
    def _strong_secret(cls, v: str) -> str:
        if v and len(v) < 32:
            raise ValueError("secret must have at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


ALWAYS_MFA_ROLES = frozenset({"access_manager"})  # whoever can grant roles always needs a second factor, whatever MFA_REQUIRED_ROLES says (ADR-0031)


def required_mfa_roles(settings: Settings) -> frozenset[str]:
    """Parsed MFA_REQUIRED_ROLES. An unknown role name is a configuration error (a typo must not silently weaken the policy)."""
    from app.core.security import ROLE_PERMISSIONS  # lazy: security imports settings

    roles = frozenset(r.strip() for r in settings.mfa_required_roles.split(",") if r.strip())
    unknown = roles - set(ROLE_PERMISSIONS)
    if unknown:
        raise RuntimeError(f"MFA_REQUIRED_ROLES has unknown roles: {sorted(unknown)}")
    return roles | ALWAYS_MFA_ROLES
