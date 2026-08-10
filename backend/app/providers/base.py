"""LogProvider: the abstraction everything else (API routes, WS tailing) is
built on. LocalFileProvider and SshFileProvider both implement it; adding a
future source (journalctl, docker logs, ...) means adding a new provider
module + a registry.py entry — nothing in api/ or tailing/ needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.models.log_source import LogSource

# Safety caps shared by all providers — a monitoring tool should never hang or
# exhaust memory/fds resolving a pattern against a huge or misconfigured tree.
MAX_RESOLVED_FILES = 500
MAX_WALK_ENTRIES = 20000


@dataclass
class ResolvedFile:
    path: str
    size: int | None = None
    mtime: float | None = None
    # Non-fatal, provider-specific heads-up about this result (e.g. journal
    # mode warning that the current user may not have full journal access).
    # None for the overwhelming majority of resolved files.
    warning: str | None = None


@dataclass
class DirEntry:
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    mtime: float | None = None
    # rwx-style permission string (e.g. "-rw-r--r--"), when the provider can
    # cheaply obtain it — powers the file picker's "will I actually be able
    # to read this?" column, so that's visible before picking a file rather
    # than only discovered once tailing fails.
    permissions: str | None = None
    # Best-effort "can the connected user read this file's *content*", for
    # files only (None for directories — being listed already proves you
    # could read the directory). None means "couldn't determine".
    readable: bool | None = None


class LogProvider(ABC):
    @abstractmethod
    async def resolve_sources(self, log_source: LogSource) -> tuple[list[ResolvedFile], bool]:
        """Return (matched files, truncated) for a log source's path/pattern."""

    @abstractmethod
    async def read_tail(self, path: str, n_lines: int) -> list[str]:
        """Return up to the last n_lines of `path`, for initial backfill context."""

    @abstractmethod
    def tail(self, path: str) -> AsyncIterator[str]:
        """Yield new lines appended to `path` as they arrive, forever (until cancelled)."""

    @abstractmethod
    async def list_directory(self, path: str) -> tuple[list[DirEntry], bool]:
        """List one directory's immediate contents (dirs first, then files, both
        alphabetically) — powers the log-source file picker. Returns
        (entries, truncated).
        """

    @abstractmethod
    async def default_browse_path(self) -> str:
        """A sensible starting directory for the file picker (e.g. the SSH
        user's home directory, or "/" locally)."""
