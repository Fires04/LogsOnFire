"""A TailSession owns exactly one real 'follow this file' operation — local
polling or a remote `tail -F` — no matter how many WebSocket subscribers are
watching it (that de-duplication lives in tailing/manager.py). It keeps a
bounded ring buffer of recent lines, used both as backfill context for
newly-attached subscribers and as the corpus the grep bar searches.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque

from app.config import get_settings
from app.models.host import Host, HostCredential
from app.providers.base import LogProvider
from app.providers.local import LocalFileProvider
from app.providers.ssh import SshFileProvider
from app.ssh.pool import get_ssh_pool
from app.tailing.broker import LineBroker, TailClosed, TailError, TailLine

logger = logging.getLogger("logsonfire.tailing.session")


class TailSession:
    def __init__(self, key: str, host: Host, credential: HostCredential | None, path: str) -> None:
        self.key = key
        self.host = host
        self.credential = credential
        self.path = path
        self.broker = LineBroker()

        settings = get_settings()
        self.buffer: deque[str] = deque(maxlen=settings.log_buffer_max_lines)
        self.subscriber_count = 0
        self.status = "starting"  # starting | running | error | closed
        self.error_message: str | None = None

        self._provider: LogProvider | None = None
        self._task: asyncio.Task | None = None
        self._used_pool = False

    async def start(self) -> None:
        """Connect and load the initial backfill. Raises on failure (e.g. bad
        credentials, unreachable host, missing file) — the caller
        (tailing/manager.py) is expected to not register a session that
        failed to start. Only once this returns successfully does the
        long-running follow loop begin in the background.
        """
        settings = get_settings()
        try:
            if self.host.connection_type == "ssh":
                conn = await get_ssh_pool().acquire(self.host, self.credential)
                self._used_pool = True
                self._provider = SshFileProvider(self.host, self.credential, connection=conn)
            else:
                self._provider = LocalFileProvider()

            backfill = await self._provider.read_tail(self.path, settings.log_buffer_max_lines)
            self.buffer.extend(backfill)
            self.status = "running"
        except Exception:
            self.status = "error"
            if self._used_pool:
                await get_ssh_pool().release(self.host.id)
            raise

        self._task = asyncio.create_task(self._follow(), name=f"tail:{self.key}")

    async def _follow(self) -> None:
        assert self._provider is not None
        try:
            async for line in self._provider.tail(self.path):
                self.buffer.append(line)
                self.broker.publish(TailLine(line))
            self.status = "closed"
            self.broker.publish(TailClosed("stopped"))
        except asyncio.CancelledError:
            self.status = "closed"
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced to subscribers, not raised further
            logger.warning("tail session %s failed: %s", self.key, exc)
            self.status = "error"
            self.error_message = str(exc)
            self.broker.publish(TailError(str(exc)))
            self.broker.publish(TailClosed("error"))
        finally:
            if self._used_pool:
                await get_ssh_pool().release(self.host.id)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
