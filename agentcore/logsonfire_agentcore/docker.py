"""Shared helpers for the "docker" log source mode — tailing a single
container's logs via `docker logs`, instead of a text file or the systemd
journal. LocalFileProvider dispatches to these when a log source's
resolved path starts with DOCKER_PREFIX, exactly mirroring how "journal"
mode is dispatched (see journal.py) — same pattern, different backend.

Note: JOURNAL_PREFIX-style deduplication doesn't apply here — each docker
log source names exactly one container, there's no "whole journal"
equivalent (docker has no single command that merges every container's
logs into one stream).

Requires the agent's own OS user to be in the 'docker' group (or running
as root) to reach the daemon socket — that's a materially more powerful
grant than the journal group (anyone in 'docker' can trivially get root on
the host via a bind-mounted container), so unlike journal access it is
NOT added automatically by install.sh; the installer asks explicitly.
"""
from __future__ import annotations

DOCKER_PREFIX = "docker://"


def make_docker_path(container: str) -> str:
    return f"{DOCKER_PREFIX}{container.strip()}"


def docker_container_from_path(path: str) -> str | None:
    if not path.startswith(DOCKER_PREFIX):
        return None
    return path[len(DOCKER_PREFIX):]


def docker_logs_args(container: str, *, follow: bool, n_lines: int | None) -> list[str]:
    """Build `docker logs`'s argument list (excluding the program name
    itself) — always a plain arg list, run via create_subprocess_exec (no
    shell). `--tail 0` when following: the initial backfill is a separate
    read_tail() call (same split as journal mode), so follow should only
    ever emit lines from this point forward, not replay history too.
    """
    args = ["logs", "--timestamps"]
    if follow:
        args += ["--tail", "0", "--follow"]
    elif n_lines is not None:
        args += ["--tail", str(int(n_lines))]
    args.append(container)
    return args
