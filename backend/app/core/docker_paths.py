"""The "docker://<container>" path convention used in the /ws/logs protocol
to refer to a single Docker container's logs instead of a real file path or
a journal unit. Pure string convention, zero I/O — kept here (not in
agentcore) because ws_logs.py needs it server-side to build a deterministic
path for "docker" mode log sources without asking the agent, mirroring
core/journal_paths.py exactly. agentcore/logsonfire_agentcore/docker.py
defines the same tiny convention on the agent side (duplicated on purpose —
the two packages don't share code, agentcore has zero dependency on the
backend).
"""
from __future__ import annotations

DOCKER_PREFIX = "docker://"


def make_docker_path(container: str) -> str:
    return f"{DOCKER_PREFIX}{container.strip()}"


def docker_container_from_path(path: str) -> str | None:
    if not path.startswith(DOCKER_PREFIX):
        return None
    return path[len(DOCKER_PREFIX):]
