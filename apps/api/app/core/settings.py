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

    @field_validator("jwt_secret")
    @classmethod
    def _strong_secret(cls, v: str) -> str:
        if v and len(v) < 32:
            raise ValueError("JWT_SECRET must have at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
