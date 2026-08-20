"""The server's own version — read from installed package metadata
(backend/pyproject.toml's `version`) rather than a second hardcoded
constant, so it can't drift from what's actually installed. Exposed via
GET /api/health (unauthenticated — the login screen shows it before any
session exists) and used to flag agents whose self-reported agent_version
doesn't match, e.g. after a server upgrade the agent hasn't picked up yet
(see CLAUDE.md's --force-reinstall gotcha).
"""
from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version


@lru_cache
def get_server_version() -> str:
    try:
        return version("logsonfire")
    except PackageNotFoundError:
        return "0.0.0-dev"
