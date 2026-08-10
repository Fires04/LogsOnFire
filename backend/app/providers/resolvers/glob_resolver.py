"""Safe glob expansion for local filesystem paths.

Uses Python's stdlib `glob` module directly against the filesystem — never a
subprocess or shell — so shell metacharacters in the pattern (`;`, backticks,
`$(...)`) have no special meaning beyond glob syntax itself.
"""
from __future__ import annotations

import glob as _glob
import os

from app.providers.base import MAX_RESOLVED_FILES


def expand_local_glob(pattern: str) -> tuple[list[str], bool]:
    """Expand `pattern` (supports `*`, `?`, `**` recursive) against the local
    filesystem. Consumption is bounded so a pattern matching a huge tree
    (e.g. an overly broad `**`) can't make this hang or exhaust memory.
    """
    matches: list[str] = []
    truncated = False
    for p in _glob.iglob(pattern, recursive=True):
        if not os.path.isfile(p):
            continue
        if len(matches) >= MAX_RESOLVED_FILES:
            truncated = True
            break
        matches.append(p)
    matches.sort()
    return matches, truncated
