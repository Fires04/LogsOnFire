"""The server's own version — read from installed package metadata
(backend/pyproject.toml's `version`) rather than a second hardcoded
constant, so it can't drift from what's actually installed. Exposed via
GET /api/health (unauthenticated — the login screen shows it before any
session exists).

The agent's *expected* version is tracked separately, not compared
against the server's own version. Agent code (agent/, agentcore/) changes
far less often than the backend/frontend — a purely cosmetic frontend
commit or an unrelated backend fix shouldn't make every already-current
agent look "out of date" and demand a reinstall. The Dockerfile's
`gitinfo` stage derives the agent's version by counting commits under
agent/agentcore only (see Dockerfile comments), and drops the result at
`app/static/agent/VERSION` — this is what a freshly-built agent package
actually gets stamped with, so it's the correct thing to compare a
connected agent's self-reported version against.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_AGENT_VERSION_FILE = Path(__file__).resolve().parent.parent / "static" / "agent" / "VERSION"


@lru_cache
def get_server_version() -> str:
    try:
        return version("logsonfire")
    except PackageNotFoundError:
        return "0.0.0-dev"


@lru_cache
def get_expected_agent_version() -> str | None:
    """The version a freshly-built agent package from this server would
    report. None outside a real Docker build (local dev has no
    static/agent/VERSION file) — mismatch checks treat that as "unknown,
    don't flag" rather than "always mismatched"."""
    try:
        return _AGENT_VERSION_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None
