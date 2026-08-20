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
    # If left empty, an ephemeral key is generated at startup with a loud warning.
    jwt_secret: str = ""  # HS256 signing secret
    # HMAC key for hashing agent bearer tokens (security/agent_tokens.py).
    # Losing/rotating it invalidates every agent's stored token hash (forces
    # reissuing tokens) but — unlike the old MASTER_KEY — loses no log data
    # or configuration, since it never encrypts anything reversibly.
    agent_token_pepper: str = ""

    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    # "Remember me" at login extends the refresh token (and therefore how
    # long the browser can go without re-entering a password — access
    # tokens stay short-lived either way and just get silently refreshed,
    # see api/routes/auth.py's /refresh) out to this instead of the
    # default above.
    remember_me_ttl_days: int = 30

    # First-boot admin seed (only used if the users table is empty)
    admin_email: str = "admin@example.com"
    admin_password: str = ""  # if empty, a random password is generated and printed once

    # Reverse proxy
    trusted_proxy: bool = False

    # Log tailing
    log_buffer_max_lines: int = 20000  # ring buffer cap per tailed file (10k-25k recommended)

    # Agent connections (ws_agent.py / agents/heartbeat.py)
    agent_heartbeat_interval_seconds: int = 30  # how often the server pings a connected agent
    agent_heartbeat_timeout_seconds: int = 90  # no pong within this window -> connection is dropped
    agent_request_timeout_seconds: float = 10.0  # resolve/browse/start_tail reply timeout

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
