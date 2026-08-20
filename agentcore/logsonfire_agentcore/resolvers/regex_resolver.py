"""Safe regex-based log discovery: walk a base directory and keep files
whose path relative to that base directory matches a regex.

The regex is only ever evaluated in Python against filenames already listed
through a safe directory-listing call (os.scandir) — it never touches a
shell, so it cannot be used to execute anything, regardless of what the
base_dir or pattern strings contain.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from logsonfire_agentcore.base import MAX_RESOLVED_FILES, MAX_WALK_ENTRIES, ResolvedFile

# (name, is_dir) pairs for one directory
ListDirFn = Callable[[str], Awaitable[list[tuple[str, bool]]]]
# (size, mtime) for one file, best-effort — either may be None if unavailable
StatFn = Callable[[str], Awaitable[tuple[int | None, float | None]]]


async def resolve_by_regex(
    base_dir: str, pattern: str, list_dir: ListDirFn, stat_file: StatFn
) -> tuple[list[ResolvedFile], bool]:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex: {exc}") from exc

    base_dir = base_dir.rstrip("/") or "/"
    base_prefix_len = len(base_dir) + 1

    results: list[ResolvedFile] = []
    truncated = False
    visited = 0
    stack = [base_dir]

    while stack and not truncated:
        current = stack.pop()
        try:
            entries = await list_dir(current)
        except OSError:
            continue

        for name, is_dir in entries:
            visited += 1
            if visited > MAX_WALK_ENTRIES:
                truncated = True
                break

            full = f"{current}/{name}"
            if is_dir:
                stack.append(full)
                continue

            rel = full[base_prefix_len:] if len(full) > base_prefix_len else name
            if not (regex.search(rel) or regex.search(name)):
                continue
            if len(results) >= MAX_RESOLVED_FILES:
                truncated = True
                break
            size, mtime = await stat_file(full)
            results.append(ResolvedFile(full, size, mtime))

    results.sort(key=lambda r: r.path)
    return results, truncated
