"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # General
    env: str = "development"  # "development" | "production"
    app_name: str = "LogsOnFire"

    # Database
    db_path: str = "./data/logsonfire.db"

    # Security secrets — MUST be set explicitly in production.
    # If left empty, an ephemeral key is generated at startup with a loud warning
    # (data encrypted with it becomes unreadable after restart).
    master_key: str = ""  # base64-encoded 32 bytes, used for AES-256-GCM credential encryption
    jwt_secret: str = ""  # HS256 signing secret

    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7

    # First-boot admin seed (only used if the users table is empty)
    admin_email: str = "admin@example.com"
    admin_password: str = ""  # if empty, a random password is generated and printed once

    # Reverse proxy
    trusted_proxy: bool = False

    # Log tailing
    log_buffer_max_lines: int = 20000  # ring buffer cap per tailed file (10k-25k recommended)
    ssh_connect_timeout_seconds: int = 10
    ssh_idle_eviction_seconds: int = 300

    # CORS / cookies
    cookie_domain: str | None = None

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def db_url(self) -> str:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
