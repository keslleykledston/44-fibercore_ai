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
    rbac_database_url: str = ""  # role fibercore_rbac: the ONLY connection that may change a membership role (empty => role changes answer 503)
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
    # ADR-0031: permissions marked `mfa_recent` in the catalog need a second factor proved in the last `mfa_recent_seconds` (login with MFA or a
    # step-up). OFF by default (owner decision 2026-10-30: the second factor is asked at LOGIN, not on every action); the machinery stays for a
    # provider that wants it back (MFA_RECENT_ENFORCE=true). /v1/auth/me reports whether it is on.
    mfa_recent_enforce: bool = False
    mfa_recent_seconds: int = Field(default=600, ge=60, le=3600)
    trusted_proxy: bool = False  # trust X-Forwarded-For (set only behind our own reverse proxy)
    job_signing_key: str = Field(default="", repr=False)  # base64 Ed25519 seed; empty => dispatch disabled (fail closed)
    # ADR-0033 (ERP Hub): where the operator places each connection's credentials (<dir>/<tenant_id>/<secret_ref>.json, mode 0600) and which ERP hosts may be
    # reached. Both empty = no ERP connection can be created or tested (fail closed).
    erp_secrets_dir: str = ""
    erp_allowed_hosts: str = ""   # comma-separated: exact hosts or *.suffix
    erp_auth_per_minute: int = Field(default=10, ge=1, le=25)   # HubSoft authentications per minute for the WHOLE deployment (the vendor's limit, 30/min, is per egress IP)
    # Per-agent intake limit (app/core/ratelimit.py): a token bucket per (tenant, Edge) on the data-intake routes. The defaults sit far above a healthy Edge (a handful of batches a minute).
    edge_ingest_burst: int = Field(default=30, ge=1, le=1000)
    edge_ingest_per_minute: int = Field(default=120, ge=1, le=6000)
    # Who the limit applies to. "capable" (default, safe under version skew): only an Edge that announces it understands a 429 (header X-Edge-Backoff: retry-after, sent by Edges that treat 429 as
    # "wait, do not count an attempt"); an older Edge would count the 429 as a failed attempt and could dead-letter good data, so it is never limited. "all": every agent (set it once every Edge is
    # updated and verified). "off": no limit.
    edge_ingest_limit: str = Field(default="capable", pattern="^(off|capable|all)$")
    # ADR-0047 D3 (fatia B): technical limits per organization. These are the DEFAULTS; the platform operator overrides them per organization (table tenant_limits). Server protection, not billing.
    limit_default_edges: int = Field(default=25, ge=0, le=10000)
    limit_default_olts: int = Field(default=250, ge=0, le=100000)
    limit_default_members: int = Field(default=200, ge=0, le=10000)
    # One bucket per ORGANIZATION on the intake routes (all its Edges together), on top of the per-agent one above: a tenant with many agents cannot starve the others.
    org_ingest_burst: int = Field(default=300, ge=1, le=10000)
    org_ingest_per_minute: int = Field(default=1200, ge=1, le=60000)
    # ADR-0048 (fatia C): transactional e-mail, configured by the PLATFORM environment (never per organization). All three of host, from and public base URL must be set, else e-mail does not exist
    # (the API behaves as before: the link is shown on screen). TLS is always on (STARTTLS or implicit SSL); there is no plaintext option.
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: str = Field(default="starttls", pattern="^(starttls|ssl)$")
    smtp_user: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_from: str = Field(default="", pattern=r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$")
    smtp_from_name: str = Field(default="FiberCore", max_length=60)
    # where the people open the app: the origin of every e-mailed link
    public_base_url: str = Field(default="", pattern=r"^$|^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$|^http://(localhost|127\.0\.0\.1)(:[0-9]{1,5})?$")
    pii_hmac_key: str = Field(default="", repr=False)  # HMAC key for customer documents; import fails closed without it
    # ADR-0043: bearer token that opens GET /metrics (Prometheus scrape). Empty (default) => the route answers 404 as if it did not exist (fail closed).
    metrics_token: str = Field(default="", repr=False)

    @field_validator("jwt_secret", "jwt_secret_previous", "pii_hmac_key", "metrics_token")
    @classmethod
    def _strong_secret(cls, v: str) -> str:
        if v and len(v) < 32:
            raise ValueError("secret must have at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


ALWAYS_MFA_ROLES = frozenset({"access_manager", "platform_support"})  # whoever can grant roles, and every platform delegate, always needs a second factor, whatever MFA_REQUIRED_ROLES says (ADR-0031)


def required_mfa_roles(settings: Settings) -> frozenset[str]:
    """Parsed MFA_REQUIRED_ROLES. An unknown role name is a configuration error (a typo must not silently weaken the policy)."""
    from app.core.security import ROLE_PERMISSIONS  # lazy: security imports settings

    roles = frozenset(r.strip() for r in settings.mfa_required_roles.split(",") if r.strip())
    unknown = roles - set(ROLE_PERMISSIONS)
    if unknown:
        raise RuntimeError(f"MFA_REQUIRED_ROLES has unknown roles: {sorted(unknown)}")
    return roles | ALWAYS_MFA_ROLES
