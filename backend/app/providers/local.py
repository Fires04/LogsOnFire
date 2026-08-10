"""Reads logs from the filesystem the LogsOnFire process itself runs on
(mounted volumes, sidecar containers sharing a filesystem, etc.).
"""
from __future__ import annotations

import asyncio
import grp
import os
import shutil
import stat
from collections.abc import AsyncIterator

import contextlib

from app.models.log_source import LogSource
from app.providers.base import MAX_RESOLVED_FILES, DirEntry, LogProvider, ResolvedFile
from app.providers.journal import journal_access_warning, journal_unit_from_path, journalctl_args, make_journal_path
from app.providers.resolvers.glob_resolver import expand_local_glob
from app.providers.resolvers.regex_resolver import resolve_by_regex

READ_CHUNK = 65536
POLL_INTERVAL_SECONDS = 0.4
MISSING_FILE_RETRY_SECONDS = 1.0


async def _local_list_dir(path: str) -> list[tuple[str, bool]]:
    def _scan() -> list[tuple[str, bool]]:
        with os.scandir(path) as it:
            return [(e.name, e.is_dir(follow_symlinks=False)) for e in it]

    return await asyncio.to_thread(_scan)


async def _local_stat_file(path: str) -> tuple[int | None, float | None]:
    def _stat() -> tuple[int | None, float | None]:
        try:
            st = os.stat(path)
            return st.st_size, st.st_mtime
        except OSError:
            return None, None

    return await asyncio.to_thread(_stat)


def _stat_many_sync(paths: list[str]) -> list[ResolvedFile]:
    results = []
    for p in paths:
        try:
            st = os.stat(p)
            results.append(ResolvedFile(p, st.st_size, st.st_mtime))
        except OSError:
            results.append(ResolvedFile(p, None, None))
    return results


def _read_last_lines_sync(path: str, n_lines: int, block_size: int = READ_CHUNK) -> list[str]:
    """Read up to the last n_lines of a (possibly huge) file without loading
    the whole thing into memory — seeks backward in blocks like `tail`."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        remaining = f.tell()
        blocks: list[bytes] = []
        newline_count = 0
        while remaining > 0 and newline_count <= n_lines:
            read_size = min(block_size, remaining)
            remaining -= read_size
            f.seek(remaining)
            block = f.read(read_size)
            newline_count += block.count(b"\n")
            blocks.append(block)

    data = b"".join(reversed(blocks))
    lines = data.split(b"\n")
    if remaining > 0 and lines:
        lines = lines[1:]  # first line may be a partial line cut mid-block
    if lines and lines[-1] == b"":
        lines = lines[:-1]  # trailing newline produces a spurious empty element
    return [ln.decode("utf-8", errors="replace") for ln in lines[-n_lines:]]


def _local_journal_access_warning() -> str | None:
    is_root = os.geteuid() == 0
    if is_root:
        return None
    try:
        group_names = {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except (KeyError, OSError):
        group_names = set()
    return journal_access_warning(is_root=is_root, groups=group_names)


async def _journal_read_tail_local(unit: str, n_lines: int) -> list[str]:
    args = journalctl_args(unit, follow=False, n_lines=n_lines)
    try:
        proc = await asyncio.create_subprocess_exec(
            "journalctl", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise RuntimeError("journalctl is not available on this host") from exc
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"journalctl failed: {stderr.decode('utf-8', 'replace').strip()}")
    lines = stdout.decode("utf-8", errors="replace").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


async def _journal_tail_local(unit: str) -> AsyncIterator[str]:
    args = journalctl_args(unit, follow=True, n_lines=None)
    # journalctl fully block-buffers its own stdout when it isn't a tty
    # (always true for a subprocess pipe) — without forcing line buffering,
    # live output sits unflushed in journalctl's own libc buffer instead of
    # arriving as it happens, which made live journal tailing silently
    # deliver nothing. Verified directly: plain `journalctl -f > file`
    # produced no output until the process exited; `stdbuf -oL journalctl -f`
    # flushed each line immediately.
    argv = (["stdbuf", "-oL", "journalctl"] if shutil.which("stdbuf") else ["journalctl"]) + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
    except FileNotFoundError as exc:
        raise RuntimeError("journalctl is not available on this host") from exc
    try:
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            yield raw.decode("utf-8", errors="replace").rstrip("\n")
    finally:
        if proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()


class LocalFileProvider(LogProvider):
    async def resolve_sources(self, log_source: LogSource) -> tuple[list[ResolvedFile], bool]:
        if log_source.mode == "journal":
            # No real "resolving" to do — journalctl accepts any unit name
            # without erroring, so we just hand back the one synthetic entry
            # and let read_tail/tail surface a real error if journalctl
            # itself isn't available or the unit produces nothing useful.
            # We do proactively check root/group access here though, since a
            # permission-limited journalctl doesn't error — it just quietly
            # returns less (or nothing), which looks like a bug otherwise.
            warning = await asyncio.to_thread(_local_journal_access_warning)
            return [ResolvedFile(make_journal_path(log_source.path_or_pattern), warning=warning)], False

        if log_source.mode == "exact_path":
            size, mtime = await _local_stat_file(log_source.path_or_pattern)
            if size is None:
                return [], False
            return [ResolvedFile(log_source.path_or_pattern, size, mtime)], False

        if log_source.mode == "glob":
            paths, truncated = await asyncio.to_thread(expand_local_glob, log_source.path_or_pattern)
            return await asyncio.to_thread(_stat_many_sync, paths), truncated

        if log_source.mode == "regex":
            assert log_source.regex_base_dir is not None
            return await resolve_by_regex(
                log_source.regex_base_dir, log_source.path_or_pattern, _local_list_dir, _local_stat_file
            )

        raise ValueError(f"unknown log source mode: {log_source.mode!r}")

    async def read_tail(self, path: str, n_lines: int) -> list[str]:
        unit = journal_unit_from_path(path)
        if unit is not None:
            return await _journal_read_tail_local(unit, n_lines)
        return await asyncio.to_thread(_read_last_lines_sync, path, n_lines)

    async def list_directory(self, path: str) -> tuple[list[DirEntry], bool]:
        def _list() -> tuple[list[DirEntry], bool]:
            dirs: list[DirEntry] = []
            files: list[DirEntry] = []
            truncated = False
            with os.scandir(path) as it:
                for e in it:
                    if len(dirs) + len(files) >= MAX_RESOLVED_FILES:
                        truncated = True
                        break
                    try:
                        is_dir = e.is_dir(follow_symlinks=False)
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    entry_path = os.path.join(path, e.name)
                    entry = DirEntry(
                        name=e.name,
                        path=entry_path,
                        is_dir=is_dir,
                        size=None if is_dir else st.st_size,
                        mtime=st.st_mtime,
                        permissions=stat.filemode(st.st_mode),
                        readable=None if is_dir else os.access(entry_path, os.R_OK),
                    )
                    (dirs if is_dir else files).append(entry)
            dirs.sort(key=lambda d: d.name.lower())
            files.sort(key=lambda d: d.name.lower())
            return dirs + files, truncated

        return await asyncio.to_thread(_list)

    async def default_browse_path(self) -> str:
        return "/"

    async def tail(self, path: str) -> AsyncIterator[str]:
        unit = journal_unit_from_path(path)
        if unit is not None:
            async for line in _journal_tail_local(unit):
                yield line
            return

        def _open(seek_end: bool) -> tuple[object, int]:
            fh = open(path, "rb")  # noqa: SIM115 - lifetime spans the generator
            if seek_end:
                fh.seek(0, os.SEEK_END)
            return fh, os.fstat(fh.fileno()).st_ino

        f, inode = await asyncio.to_thread(_open, True)
        pending = b""
        try:
            while True:
                chunk = await asyncio.to_thread(f.read, READ_CHUNK)
                if chunk:
                    pending += chunk
                    *complete_lines, pending = pending.split(b"\n")
                    for line in complete_lines:
                        yield line.decode("utf-8", errors="replace")
                    continue

                def _check_rotation() -> str:
                    try:
                        st = os.stat(path)
                    except FileNotFoundError:
                        return "missing"
                    if st.st_ino != inode:
                        return "rotated"
                    if st.st_size < f.tell():
                        return "truncated"
                    return "unchanged"

                status = await asyncio.to_thread(_check_rotation)
                if status == "rotated":
                    await asyncio.to_thread(f.close)
                    f, inode = await asyncio.to_thread(_open, False)
                    pending = b""
                elif status == "truncated":
                    await asyncio.to_thread(f.seek, 0)
                    pending = b""

                await asyncio.sleep(MISSING_FILE_RETRY_SECONDS if status == "missing" else POLL_INTERVAL_SECONDS)
        finally:
            await asyncio.to_thread(f.close)
