"""Reads logs from a remote host over SSH.

Two very different mechanisms are used depending on the operation:

* Discovery (glob/regex resolution, exact-path existence check) goes over
  **SFTP** (`sftp.glob()`, `sftp.listdir()`, `sftp.stat()`) — a binary
  protocol with no shell involved at all, so pattern/path strings can never
  be interpreted as commands.
* Reading file content (`read_tail`, `tail`) has to invoke the real `tail`
  binary on the remote host to avoid downloading huge files just to see the
  end of them — and the SSH "exec" channel only ever transports a single
  command *string* that the remote shell interprets (there is no argv-array
  form like a local subprocess has). The safe way to build that string is to
  `shlex.quote()` every path before interpolating it, which renders shell
  metacharacters (`;`, backticks, `$(...)`) inert literal characters inside
  quotes. We never use an f-string with a raw, unquoted path.
"""
from __future__ import annotations

import shlex
import stat
from collections.abc import AsyncIterator

import asyncssh

from app.models.host import Host, HostCredential
from app.models.log_source import LogSource
from app.providers.base import MAX_RESOLVED_FILES, DirEntry, LogProvider, ResolvedFile
from app.providers.journal import (
    journal_access_warning,
    journal_unit_from_path,
    journalctl_args,
    make_journal_path,
)
from app.providers.resolvers.regex_resolver import resolve_by_regex
from app.ssh.connect import open_ssh_connection
from app.ssh.exceptions import SshCommandError


def _quote(path: str) -> str:
    return shlex.quote(path)


def _journalctl_command(unit: str, *, follow: bool, n_lines: int | None) -> str:
    """Same shell-quoting discipline as `tail` below: every argument is
    quoted individually, so nothing in a unit name can escape into a second
    command even though this ends up as one exec string."""
    args = ["journalctl", *journalctl_args(unit, follow=follow, n_lines=n_lines)]
    quoted = " ".join(shlex.quote(a) for a in args)
    if not follow:
        return quoted
    # journalctl fully block-buffers its own stdout whenever it isn't a tty
    # (always true here — this runs over an SSH exec channel) — without
    # forcing line buffering, "live" output just sits in journalctl's libc
    # buffer, arriving in one lump (if ever) instead of as it happens. This
    # was verified directly: `journalctl -f > file` on a real host produced
    # nothing until the process exited, while `stdbuf -oL journalctl -f`
    # flushed each line immediately. `command -v` guards against remote
    # hosts without coreutils' stdbuf — better a laggy live tail there than
    # a broken command.
    return f"if command -v stdbuf >/dev/null 2>&1; then stdbuf -oL {quoted}; else {quoted}; fi"


async def _ssh_journal_access_warning(conn: asyncssh.SSHClientConnection) -> str | None:
    """Same permission check as the local provider, but against the remote
    user's id/groups. Best-effort: if `id` itself fails or isn't available,
    we stay quiet rather than block the resolve on a diagnostic side-check."""
    try:
        result = await conn.run("id -u && id -Gn", check=False)
    except Exception:  # noqa: BLE001 - diagnostic only, never fatal
        return None
    if result.exit_status != 0:
        return None
    text = result.stdout if isinstance(result.stdout, str) else result.stdout.decode("utf-8", "replace")
    lines = text.splitlines()
    if len(lines) < 2:
        return None
    is_root = lines[0].strip() == "0"
    groups = set(lines[1].split())
    return journal_access_warning(is_root=is_root, groups=groups)


async def _ssh_uid_gids(conn: asyncssh.SSHClientConnection) -> tuple[int, set[int]] | None:
    """The connected user's numeric uid + group ids, for comparing against
    SFTP-reported file ownership to guess readability. Best-effort: None if
    `id` isn't available or its output can't be parsed — callers just fall
    back to not showing a readability guess."""
    try:
        result = await conn.run("id -u && id -G", check=False)
    except Exception:  # noqa: BLE001 - diagnostic only, never fatal
        return None
    if result.exit_status != 0:
        return None
    text = result.stdout if isinstance(result.stdout, str) else result.stdout.decode("utf-8", "replace")
    lines = text.splitlines()
    if len(lines) < 2:
        return None
    try:
        uid = int(lines[0].strip())
        gids = {int(g) for g in lines[1].split()}
    except ValueError:
        return None
    return uid, gids


def _posix_readable(*, mode: int, owner_uid: int, owner_gid: int, my_uid: int, my_gids: set[int]) -> bool:
    if my_uid == 0:
        return True
    if owner_uid == my_uid:
        return bool(mode & stat.S_IRUSR)
    if owner_gid in my_gids:
        return bool(mode & stat.S_IRGRP)
    return bool(mode & stat.S_IROTH)


class SshFileProvider(LogProvider):
    """
    :param connection: an already-established, caller-owned connection to
        reuse (e.g. from ssh/pool.py). When given, this provider never opens
        or closes it — the caller (TailSession) manages its lifetime via the
        pool. When omitted, each call opens and closes its own short-lived
        connection — fine for infrequent one-off calls like resolve/preview,
        but NOT how live tailing is driven (see tailing/session.py).
    """

    def __init__(
        self,
        host: Host,
        credential: HostCredential | None,
        connection: asyncssh.SSHClientConnection | None = None,
    ):
        self.host = host
        self.credential = credential
        self._shared_connection = connection

    async def _connect(self) -> asyncssh.SSHClientConnection:
        return await open_ssh_connection(self.host, self.credential)

    async def resolve_sources(self, log_source: LogSource) -> tuple[list[ResolvedFile], bool]:
        if log_source.mode == "journal":
            # No SFTP round-trip needed for the file itself — journalctl
            # accepts any unit name without erroring, so we hand back the
            # one synthetic entry and let read_tail/tail surface a real
            # error if journalctl isn't available on the remote host or the
            # unit is bogus. We do open a connection just for a quick
            # root/group check, since a permission-limited journalctl
            # doesn't error — it silently returns less (or nothing).
            conn = self._shared_connection or await self._connect()
            try:
                warning = await _ssh_journal_access_warning(conn)
            finally:
                if conn is not self._shared_connection:
                    conn.close()
                    await conn.wait_closed()
            return [ResolvedFile(make_journal_path(log_source.path_or_pattern), warning=warning)], False

        conn = self._shared_connection or await self._connect()
        try:
            sftp = await conn.start_sftp_client()
            try:
                if log_source.mode == "exact_path":
                    try:
                        attrs = await sftp.stat(log_source.path_or_pattern)
                    except (asyncssh.SFTPError, OSError):
                        return [], False
                    return [ResolvedFile(log_source.path_or_pattern, attrs.size, attrs.mtime)], False

                if log_source.mode == "glob":
                    try:
                        names = await sftp.glob(log_source.path_or_pattern)
                    except (asyncssh.SFTPError, OSError):
                        names = []
                    truncated = len(names) > MAX_RESOLVED_FILES
                    names = sorted(names)[:MAX_RESOLVED_FILES]
                    results = []
                    for name in names:
                        try:
                            attrs = await sftp.stat(name)
                        except (asyncssh.SFTPError, OSError):
                            results.append(ResolvedFile(name, None, None))
                            continue
                        if attrs.type == asyncssh.FILEXFER_TYPE_REGULAR:
                            results.append(ResolvedFile(name, attrs.size, attrs.mtime))
                    return results, truncated

                if log_source.mode == "regex":
                    assert log_source.regex_base_dir is not None

                    async def _list_dir(path: str) -> list[tuple[str, bool]]:
                        entries = await sftp.readdir(path)
                        out = []
                        for e in entries:
                            if e.filename in (".", ".."):
                                continue
                            is_dir = e.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY
                            out.append((e.filename, is_dir))
                        return out

                    async def _stat_file(path: str) -> tuple[int | None, float | None]:
                        try:
                            attrs = await sftp.stat(path)
                        except (asyncssh.SFTPError, OSError):
                            return None, None
                        return attrs.size, attrs.mtime

                    return await resolve_by_regex(
                        log_source.regex_base_dir, log_source.path_or_pattern, _list_dir, _stat_file
                    )

                raise ValueError(f"unknown log source mode: {log_source.mode!r}")
            finally:
                sftp.exit()
                await sftp.wait_closed()
        finally:
            if conn is not self._shared_connection:
                conn.close()
                await conn.wait_closed()

    async def read_tail(self, path: str, n_lines: int) -> list[str]:
        conn = self._shared_connection or await self._connect()
        try:
            unit = journal_unit_from_path(path)
            command = (
                _journalctl_command(unit, follow=False, n_lines=n_lines)
                if unit is not None
                else f"tail -n {int(n_lines)} -- {_quote(path)}"
            )
            result = await conn.run(command, check=False)
            if result.exit_status != 0:
                what = "journalctl" if unit is not None else "remote tail"
                raise SshCommandError(f"{what} failed: {result.stderr}")
            text = result.stdout if isinstance(result.stdout, str) else result.stdout.decode("utf-8", "replace")
            lines = text.split("\n")
            if lines and lines[-1] == "":
                lines = lines[:-1]
            return lines
        finally:
            if conn is not self._shared_connection:
                conn.close()
                await conn.wait_closed()

    async def list_directory(self, path: str) -> tuple[list[DirEntry], bool]:
        conn = self._shared_connection or await self._connect()
        try:
            sftp = await conn.start_sftp_client()
            try:
                try:
                    raw_entries = await sftp.readdir(path)
                except (asyncssh.SFTPError, OSError) as exc:
                    raise SshCommandError(f"could not list {path}: {exc}") from exc

                # One round-trip for "who am I" (uid + numeric group ids),
                # reused for every entry's readability guess below — not
                # per-entry, just once per directory listing.
                whoami = await _ssh_uid_gids(conn)

                dirs: list[DirEntry] = []
                files: list[DirEntry] = []
                truncated = False
                for e in raw_entries:
                    if e.filename in (".", ".."):
                        continue
                    if len(dirs) + len(files) >= MAX_RESOLVED_FILES:
                        truncated = True
                        break
                    is_dir = e.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY
                    permissions = stat.filemode(e.attrs.permissions) if e.attrs.permissions is not None else None
                    readable = None
                    if (
                        not is_dir
                        and whoami is not None
                        and e.attrs.permissions is not None
                        and e.attrs.uid is not None
                        and e.attrs.gid is not None
                    ):
                        readable = _posix_readable(
                            mode=e.attrs.permissions,
                            owner_uid=e.attrs.uid,
                            owner_gid=e.attrs.gid,
                            my_uid=whoami[0],
                            my_gids=whoami[1],
                        )
                    entry = DirEntry(
                        name=e.filename,
                        path=f"{path.rstrip('/')}/{e.filename}",
                        is_dir=is_dir,
                        size=None if is_dir else e.attrs.size,
                        mtime=e.attrs.mtime,
                        permissions=permissions,
                        readable=readable,
                    )
                    (dirs if is_dir else files).append(entry)
                dirs.sort(key=lambda d: d.name.lower())
                files.sort(key=lambda d: d.name.lower())
                return dirs + files, truncated
            finally:
                sftp.exit()
                await sftp.wait_closed()
        finally:
            if conn is not self._shared_connection:
                conn.close()
                await conn.wait_closed()

    async def default_browse_path(self) -> str:
        conn = self._shared_connection or await self._connect()
        try:
            sftp = await conn.start_sftp_client()
            try:
                try:
                    return await sftp.realpath(".")
                except (asyncssh.SFTPError, OSError):
                    return "/"
            finally:
                sftp.exit()
                await sftp.wait_closed()
        finally:
            if conn is not self._shared_connection:
                conn.close()
                await conn.wait_closed()

    async def tail(self, path: str) -> AsyncIterator[str]:
        # Uses the shared (pooled) connection when given — this is what
        # guarantees N concurrent tails of the same host share one SSH
        # connection. Falls back to a private one-off connection otherwise.
        conn = self._shared_connection or await self._connect()
        unit = journal_unit_from_path(path)
        command = (
            _journalctl_command(unit, follow=True, n_lines=None)
            if unit is not None
            else f"tail -F -n 0 -- {_quote(path)}"
        )
        try:
            process = await conn.create_process(command, encoding="utf-8")
            try:
                async for line in process.stdout:
                    yield line.rstrip("\n")
            finally:
                process.terminate()
        finally:
            if conn is not self._shared_connection:
                conn.close()
                await conn.wait_closed()
