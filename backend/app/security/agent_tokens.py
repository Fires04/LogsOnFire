"""Agent bearer tokens.

Unlike login passwords (argon2id, see security/passwords.py), an agent
token is a 256-bit random bearer secret with no guessable structure — an
attacker gains nothing from a slow KDF that a low-entropy password defends
against. Instead we HMAC-SHA256 it with a server-side pepper and store the
hash indexed for direct O(1) lookup (`WHERE token_hash = ?`), rather than
argon2's per-row salted verify loop, which would force an O(n) scan to find
which row a given token belongs to.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from app.config import get_settings

TOKEN_PREFIX_LEN = 12


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    pepper = get_settings().agent_token_pepper.encode("utf-8")
    return hmac.new(pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()


def token_prefix(token: str) -> str:
    return token[:TOKEN_PREFIX_LEN]


def verify_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)
