"""Agent configuration: just server_url + token, read from env vars or a
TOML config file. Everything else (which log sources to watch) is owned
centrally by the server and pushed down over /ws/agent on demand — the
agent itself carries no log-source configuration of its own, so
re-pointing it at a different server is a one-line config change, not a
redeploy. See FiresLog's CLAUDE.md for the reasoning.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/logsonfire-agent/config.toml")


def _installed_agent_version() -> str:
    # Read from the installed wheel's own metadata (agent/pyproject.toml's
    # `version`) rather than a second hardcoded constant here that could
    # drift from it — this value is what the server compares against its
    # own version to flag an out-of-date agent (see CLAUDE.md's
    # --force-reinstall gotcha), so it has to be trustworthy.
    try:
        return version("logsonfire-agent")
    except PackageNotFoundError:
        return "0.0.0-dev"


AGENT_VERSION = _installed_agent_version()


@dataclass
class AgentConfig:
    server_url: str  # e.g. "wss://logs.example.com" (no trailing /ws/agent)
    token: str
    agent_version: str = AGENT_VERSION

    @property
    def ws_url(self) -> str:
        return self.server_url.rstrip("/") + "/ws/agent"


def load_config(path: Path | None = None) -> AgentConfig:
    path = path or DEFAULT_CONFIG_PATH
    data: dict = {}
    if path.is_file():
        data = tomllib.loads(path.read_text())

    server_url = os.environ.get("LOGSONFIRE_SERVER_URL") or data.get("server_url")
    token = os.environ.get("LOGSONFIRE_AGENT_TOKEN") or data.get("token")
    if not server_url or not token:
        raise RuntimeError(
            "Agent needs a server URL and a token, from env vars "
            "LOGSONFIRE_SERVER_URL / LOGSONFIRE_AGENT_TOKEN, or from "
            f"[server_url, token] in {path}. Generate a token from the "
            "server's Agents page (\"+ New agent\")."
        )
    return AgentConfig(server_url=server_url, token=token)
