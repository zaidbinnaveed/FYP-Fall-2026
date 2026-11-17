"""Application settings, read only from environment variables (NFR-SEC-09).

Every variable here must also appear in ``infrastructure/.env.example``; a test enforces it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# NFR-SEC-06 / CLAUDE.md: signed URLs expire in at most 10 minutes.
MAX_SIGNED_URL_TTL_SECONDS = 600


class Settings(BaseSettings):
    """Typed view of the process environment. Required values have no default."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Database (PostgreSQL 16 + pgvector). Required.
    database_url: SecretStr

    # Object storage (S3-compatible). Required.
    storage_endpoint_url: str
    storage_public_endpoint_url: str
    storage_region: str = "us-east-1"
    storage_bucket: str = Field(min_length=3, max_length=63)
    storage_access_key_id: SecretStr
    storage_secret_access_key: SecretStr
    storage_signed_url_ttl_seconds: int = Field(default=MAX_SIGNED_URL_TTL_SECONDS, gt=0)

    # Internal services.
    inference_url: str = "http://inference:8001"

    # Worker.
    worker_poll_interval_seconds: int = Field(default=60, gt=0)
    worker_heartbeat_file: str = "/tmp/oscc-worker-heartbeat"  # noqa: S108 - container-local file

    # Dependency probe timeout used by /readyz.
    readiness_timeout_seconds: float = Field(default=2.0, gt=0)

    @field_validator("storage_signed_url_ttl_seconds")
    @classmethod
    def _ttl_within_limit(cls, value: int) -> int:
        if value > MAX_SIGNED_URL_TTL_SECONDS:
            raise ValueError(
                "STORAGE_SIGNED_URL_TTL_SECONDS must be "
                f"<= {MAX_SIGNED_URL_TTL_SECONDS} (NFR-SEC-06)"
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process. Fails fast if a required variable is missing."""
    return Settings()
