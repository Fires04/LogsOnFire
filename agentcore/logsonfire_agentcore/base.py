"""Shared types for local log-source reading. Zero FastAPI/SQLAlchemy
dependency on purpose — this package runs inside the agent process on a
monitored host, not inside the server, so it must not pull in the backend's
web/DB stack. `LogSourceSpec` replaces the backend's SQLAlchemy `LogSource`
ORM model as the input to `resolve_sources()` — just the three fields that
actually matter for resolving a pattern into files.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

# Safety caps — resolving a pattern against a huge or misconfigured tree
# should never hang the agent or exhaust its memory/fds.
MAX_RESOLVED_FILES = 500
MAX_WALK_ENTRIES = 20000


@dataclass
class LogSourceSpec:
    mode: str  # "exact_path" | "glob" | "regex" | "journal"
    path_or_pattern: str
    regex_base_dir: str | None = None


@dataclass
class ResolvedFile:
    path: str
    size: int | None = None
    mtime: float | None = None
    warning: str | None = None


@dataclass
class DirEntry:
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    mtime: float | None = None
    permissions: str | None = None
    readable: bool | None = None


class LogProvider(ABC):
    """Deliberately small ABC — kept from the original server-side design
    (see FiresLog's CLAUDE.md) even though LocalFileProvider is the only
    implementation now that pull-over-SSH is gone: a future source (docker
    logs, a different log framework) is a new module implementing this,
    not a special case scattered through dispatch.py.
    """

    @abstractmethod
    async def resolve_sources(self, spec: LogSourceSpec) -> tuple[list[ResolvedFile], bool]:
        """Return (matched files, truncated) for a log source's path/pattern."""

    @abstractmethod
    async def read_tail(self, path: str, n_lines: int) -> list[str]:
        """Return up to the last n_lines of `path`, for initial backfill context."""

    @abstractmethod
    def tail(self, path: str) -> AsyncIterator[str]:
        """Yield new lines appended to `path` as they arrive, forever (until cancelled)."""

    @abstractmethod
    async def list_directory(self, path: str) -> tuple[list[DirEntry], bool]:
        """List one directory's immediate contents (dirs first, then files,
        both alphabetically). Returns (entries, truncated)."""

    @abstractmethod
    async def default_browse_path(self) -> str:
        """A sensible starting directory for the file picker."""
