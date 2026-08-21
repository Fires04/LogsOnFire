"""Reads logs from the filesystem the agent process itself runs on — the
monitored host. This is the only LogProvider implementation now that
pull-over-SSH is gone (see FiresLog's CLAUDE.md gotchas): the server never
touches this host's filesystem directly, everything goes through the agent.
"""
from __future__ import annotations

import asyncio
import contextlib
import grp
import os
import shutil
import stat
from collections.abc import AsyncIterator

from logsonfire_agentcore.base import MAX_RESOLVED_FILES, DirEntry, LogProvider, LogSourceSpec, ResolvedFile
from logsonfire_agentcore.docker import docker_container_from_path, docker_logs_args, make_docker_path
from logsonfire_agentcore.journal import journal_access_warning, journal_unit_from_path, journalctl_args, make_journal_path
from logsonfire_agentcore.resolvers.glob_resolver import expand_local_glob
from logsonfire_agentcore.resolvers.regex_resolver import resolve_by_regex

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


async def _docker_access_check(container: str) -> str | None:
    """Returns a warning string if something's off (docker not installed,
    daemon unreachable/no permission, or the named container doesn't
    currently exist), else None. `docker inspect` covers both running and
    stopped containers, so a stopped-but-real container isn't reported as
    missing."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{.State.Status}}", container,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return "docker is not installed on this host"
    _, stderr = await proc.communicate()
    if proc.returncode == 0:
        return None
    err = stderr.decode("utf-8", "replace").strip().lower()
    if "permission denied" in err or "dial unix" in err or "connect:" in err:
        return (
            "Could not reach the Docker daemon — the agent's user is probably not in the "
            "'docker' group. Add it with: usermod -aG docker logsonfire-agent "
            "(then: systemctl restart logsonfire-agent)."
        )
    return f"No container named '{container}' found (checked both running and stopped containers)."


async def _docker_read_tail_local(container: str, n_lines: int) -> list[str]:
    args = docker_logs_args(container, follow=False, n_lines=n_lines)
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
    except FileNotFoundError as exc:
        raise RuntimeError("docker is not installed on this host") from exc
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"docker logs failed: {stdout.decode('utf-8', 'replace').strip()}")
    lines = stdout.decode("utf-8", errors="replace").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


async def _docker_tail_local(container: str) -> AsyncIterator[str]:
    args = docker_logs_args(container, follow=True, n_lines=None)
    # Unlike journalctl, `docker logs -f` streams from the daemon's API as
    # received rather than through a buffered file read — not observed to
    # need stdbuf-style forcing during testing, but noted here in case a
    # future regression turns up the same class of "live but not really
    # live" bug journal mode had.
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
    except FileNotFoundError as exc:
        raise RuntimeError("docker is not installed on this host") from exc
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


async def _journal_tail_local(unit: str) -> AsyncIterator[str]:
    args = journalctl_args(unit, follow=True, n_lines=None)
    # journalctl fully block-buffers its own stdout when it isn't a tty
    # (always true for a subprocess pipe) — without forcing line buffering,
    # live output sits unflushed until the process exits. See FiresLog's
    # CLAUDE.md gotcha list — verified directly, not a hypothetical.
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


async def _list_journal_units_local() -> list[str]:
    """Known systemd service units on this host (loaded at some point, not
    just currently running) — powers a picker in the log source form so a
    unit name doesn't have to be typed from memory. `list-units --all`
    without `--state` still only shows units systemd has loaded at least
    once this boot; that's the same set journalctl can meaningfully filter
    on, so it's the right list to offer."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager", "--plain",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("systemctl is not available on this host") from exc
    stdout, stderr = await proc.communicate()
    # returncode 1 just means "some listed units are inactive/failed" here,
    # not a real failure — systemctl still printed a valid unit list.
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"systemctl list-units failed: {stderr.decode('utf-8', 'replace').strip()}")
    units: list[str] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        name = line.split(None, 1)[0].strip() if line.strip() else ""
        if name.endswith(".service"):
            units.append(name)
    return sorted(set(units))


async def _list_docker_containers_local() -> list[str]:
    """Container names (running and stopped) — same reasoning as journal
    units above, and the same "permission denied" case surfaces as a
    RuntimeError with a message pointing at the docker group, matching
    _docker_access_check's wording."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "-a", "--format", "{{.Names}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("docker is not installed on this host") from exc
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace").strip().lower()
        if "permission denied" in err or "dial unix" in err or "connect:" in err:
            raise RuntimeError(
                "Could not reach the Docker daemon — the agent's user is probably not in the "
                "'docker' group. Add it with: usermod -aG docker logsonfire-agent "
                "(then: systemctl restart logsonfire-agent)."
            )
        raise RuntimeError(f"docker ps failed: {stderr.decode('utf-8', 'replace').strip()}")
    names = [n.strip() for n in stdout.decode("utf-8", errors="replace").splitlines() if n.strip()]
    return sorted(set(names))


class LocalFileProvider(LogProvider):
    async def resolve_sources(self, spec: LogSourceSpec) -> tuple[list[ResolvedFile], bool]:
        if spec.mode == "journal":
            # No real "resolving" to do — journalctl accepts any unit name
            # without erroring, so we just hand back the one synthetic entry
            # and let read_tail/tail surface a real error if journalctl
            # itself isn't available or the unit produces nothing useful.
            warning = await asyncio.to_thread(_local_journal_access_warning)
            return [ResolvedFile(make_journal_path(spec.path_or_pattern), warning=warning)], False

        if spec.mode == "docker":
            # Unlike journal, container names are typo-prone and dynamic
            # (removed/recreated often), so this actually checks the
            # container exists and the daemon is reachable, surfacing
            # either as a warning rather than silently returning nothing.
            warning = await _docker_access_check(spec.path_or_pattern)
            return [ResolvedFile(make_docker_path(spec.path_or_pattern), warning=warning)], False

        if spec.mode == "exact_path":
            size, mtime = await _local_stat_file(spec.path_or_pattern)
            if size is None:
                return [], False
            return [ResolvedFile(spec.path_or_pattern, size, mtime)], False

        if spec.mode == "glob":
            paths, truncated = await asyncio.to_thread(expand_local_glob, spec.path_or_pattern)
            return await asyncio.to_thread(_stat_many_sync, paths), truncated

        if spec.mode == "regex":
            assert spec.regex_base_dir is not None
            return await resolve_by_regex(spec.regex_base_dir, spec.path_or_pattern, _local_list_dir, _local_stat_file)

        raise ValueError(f"unknown log source mode: {spec.mode!r}")

    async def read_tail(self, path: str, n_lines: int) -> list[str]:
        unit = journal_unit_from_path(path)
        if unit is not None:
            return await _journal_read_tail_local(unit, n_lines)
        container = docker_container_from_path(path)
        if container is not None:
            return await _docker_read_tail_local(container, n_lines)
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
        return os.path.expanduser("~") or "/"

    async def list_journal_units(self) -> list[str]:
        return await _list_journal_units_local()

    async def list_docker_containers(self) -> list[str]:
        return await _list_docker_containers_local()

    async def tail(self, path: str) -> AsyncIterator[str]:
        unit = journal_unit_from_path(path)
        if unit is not None:
            async for line in _journal_tail_local(unit):
                yield line
            return

        container = docker_container_from_path(path)
        if container is not None:
            async for line in _docker_tail_local(container):
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
