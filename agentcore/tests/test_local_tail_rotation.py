"""Log rotation handling in LocalFileProvider.tail(): a monitoring tool must
keep following a file across both rename-based rotation (logrotate's default
`create`/`copytruncate`-adjacent rename+recreate) and in-place truncation
(e.g. `> file.log`), the same way `tail -F` does — otherwise a rotated log
silently goes stale mid-incident, which is exactly the wrong moment.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from logsonfire_agentcore.local import LocalFileProvider


async def _collect_lines(gen, count: int, timeout: float = 5.0) -> list[str]:
    result = []
    async with asyncio.timeout(timeout):
        async for line in gen:
            result.append(line)
            if len(result) >= count:
                break
    return result


async def test_tail_follows_lines_appended_after_open(tmp_path: Path):
    f = tmp_path / "app.log"
    f.write_text("")
    provider = LocalFileProvider()
    gen = provider.tail(str(f))

    async def writer():
        await asyncio.sleep(0.6)  # let tail() open and seek to end first
        with open(f, "a") as fh:
            fh.write("line1\n")
            fh.write("line2\n")

    lines, _ = await asyncio.gather(_collect_lines(gen, 2), writer())
    assert lines == ["line1", "line2"]
    await gen.aclose()


async def test_tail_follows_rename_based_rotation(tmp_path: Path):
    f = tmp_path / "app.log"
    f.write_text("before rotation\n")
    provider = LocalFileProvider()
    gen = provider.tail(str(f))

    async def rotate_and_write():
        await asyncio.sleep(0.6)
        os.rename(f, tmp_path / "app.log.1")  # logrotate-style rename
        with open(f, "w") as fh:  # a new file is created at the same path
            fh.write("after rotation\n")

    lines, _ = await asyncio.gather(_collect_lines(gen, 1), rotate_and_write())
    assert lines == ["after rotation"]
    await gen.aclose()


async def test_tail_follows_in_place_truncation(tmp_path: Path):
    f = tmp_path / "app.log"
    f.write_text("old content that will be truncated\n")
    provider = LocalFileProvider()
    gen = provider.tail(str(f))

    async def truncate_and_write():
        await asyncio.sleep(0.6)
        with open(f, "w") as fh:  # same inode, size drops to 0 (e.g. `> file.log`)
            fh.write("fresh content\n")

    lines, _ = await asyncio.gather(_collect_lines(gen, 1), truncate_and_write())
    assert lines == ["fresh content"]
    await gen.aclose()
