"""AES-256-GCM envelope encryption for host credentials at rest.

The master key is supplied via the MASTER_KEY env var (base64-encoded 32 bytes)
and is NEVER persisted to the database. If it is lost, every encrypted secret
in the database becomes permanently unrecoverable — this is intentional and
must be documented for operators (see README).

Ciphertext layout: nonce (12 bytes) || AESGCM(ciphertext || 16-byte tag)
"""
from __future__ import annotations

import base64
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

logger = logging.getLogger("logsonfire.crypto")

_NONCE_LEN = 12
_cached_key: bytes | None = None


def _resolve_key() -> bytes:
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    settings = get_settings()
    if settings.master_key:
        try:
            key = base64.b64decode(settings.master_key)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("MASTER_KEY is not valid base64") from exc
        if len(key) != 32:
            raise RuntimeError("MASTER_KEY must decode to exactly 32 bytes (AES-256)")
        _cached_key = key
        return key

    # No key configured: generate an ephemeral one for this process only, and
    # warn loudly — this should only ever happen in local/dev experimentation.
    key = AESGCM.generate_key(bit_length=256)
    _cached_key = key
    logger.critical(
        "MASTER_KEY is not set. Generated an EPHEMERAL encryption key for THIS "
        "PROCESS ONLY. Any host credentials encrypted now will be PERMANENTLY "
        "UNREADABLE after a restart. Set MASTER_KEY before storing real "
        "credentials (generate one with: openssl rand -base64 32). "
        "Ephemeral key for this run: %s",
        base64.b64encode(key).decode(),
    )
    return key


def reset_key_cache() -> None:
    """Test helper: force _resolve_key() to re-read settings on next call."""
    global _cached_key
    _cached_key = None


def encrypt(plaintext: bytes) -> bytes:
    key = _resolve_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt(data: bytes) -> bytes:
    key = _resolve_key()
    aesgcm = AESGCM(key)
    nonce, ciphertext = data[:_NONCE_LEN], data[_NONCE_LEN:]
    return aesgcm.decrypt(nonce, ciphertext, None)


def encrypt_str(plaintext: str) -> bytes:
    return encrypt(plaintext.encode("utf-8"))


def decrypt_str(data: bytes) -> str:
    return decrypt(data).decode("utf-8")
