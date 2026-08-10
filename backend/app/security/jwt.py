"""Access/refresh JWT issuance & verification (HS256)."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt as pyjwt

from app.config import get_settings

logger = logging.getLogger("logsonfire.jwt")

ALGORITHM = "HS256"
_cached_secret: str | None = None


def _resolve_secret() -> str:
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret
    settings = get_settings()
    if settings.jwt_secret:
        _cached_secret = settings.jwt_secret
        return _cached_secret
    _cached_secret = secrets.token_urlsafe(48)
    logger.critical(
        "JWT_SECRET is not set. Generated an EPHEMERAL signing secret for THIS "
        "PROCESS ONLY — all sessions will be invalidated on restart. Set "
        "JWT_SECRET in production."
    )
    return _cached_secret


def reset_secret_cache() -> None:
    global _cached_secret
    _cached_secret = None


TokenType = Literal["access", "refresh"]


def create_token(subject: str, token_type: TokenType, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    ttl = (
        timedelta(minutes=settings.access_token_ttl_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_ttl_days)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
    }
    if extra:
        payload.update(extra)
    return pyjwt.encode(payload, _resolve_secret(), algorithm=ALGORITHM)


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    payload = pyjwt.decode(token, _resolve_secret(), algorithms=[ALGORITHM])
    if expected_type is not None and payload.get("type") != expected_type:
        raise pyjwt.InvalidTokenError(f"expected token type {expected_type!r}, got {payload.get('type')!r}")
    return payload
