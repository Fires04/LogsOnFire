"""Reuses one SSHClientConnection per host across concurrent tails.

This is what guarantees that N browser panels/dashboards watching logs on
the same host never open more than one underlying SSH TCP connection —
each tail runs as its own channel (remote `tail -F` process) multiplexed
over that shared connection.
"""
from __future__ import annotations

import asyncio
import logging

import asyncssh

from app.config import get_settings
from app.models.host import Host, HostCredential

logger = logging.getLogger("logsonfire.ssh.pool")


class _PooledConnection:
    __slots__ = ("conn", "refcount", "evict_task")

    def __init__(self, conn: asyncssh.SSHClientConnection) -> None:
        self.conn = conn
        self.refcount = 0
        self.evict_task: asyncio.Task | None = None


class SshConnectionPool:
    def __init__(self) -> None:
        self._pool: dict[str, _PooledConnection] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, host_id: str) -> asyncio.Lock:
        lock = self._locks.get(host_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host_id] = lock
        return lock

    async def acquire(self, host: Host, credential: HostCredential | None) -> asyncssh.SSHClientConnection:
        """Return a live connection to `host`, opening one if needed. Caller
        MUST call release(host.id) exactly once when done with it."""
        from app.ssh.connect import open_ssh_connection  # local import: avoid import cycle

        async with self._lock_for(host.id):
            pooled = self._pool.get(host.id)
            if pooled is not None and not pooled.conn.is_closed():
                if pooled.evict_task is not None:
                    pooled.evict_task.cancel()
                    pooled.evict_task = None
                pooled.refcount += 1
                return pooled.conn

            conn = await open_ssh_connection(host, credential)
            pooled = _PooledConnection(conn)
            pooled.refcount = 1
            self._pool[host.id] = pooled
            logger.info("opened pooled SSH connection to host %s (%s)", host.id, host.hostname)
            return conn

    async def release(self, host_id: str) -> None:
        async with self._lock_for(host_id):
            pooled = self._pool.get(host_id)
            if pooled is None:
                return
            pooled.refcount = max(0, pooled.refcount - 1)
            if pooled.refcount == 0:
                delay = get_settings().ssh_idle_eviction_seconds
                pooled.evict_task = asyncio.ensure_future(self._evict_after_idle(host_id, delay))

    async def _evict_after_idle(self, host_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        async with self._lock_for(host_id):
            pooled = self._pool.get(host_id)
            if pooled is not None and pooled.refcount == 0:
                logger.info("closing idle pooled SSH connection to host %s", host_id)
                del self._pool[host_id]
                pooled.conn.close()
                await pooled.conn.wait_closed()

    async def evict(self, host_id: str) -> None:
        """Force-close and drop a host's pooled connection immediately
        (e.g. after a credential/host-key change makes it stale)."""
        async with self._lock_for(host_id):
            pooled = self._pool.pop(host_id, None)
            if pooled is not None:
                if pooled.evict_task is not None:
                    pooled.evict_task.cancel()
                pooled.conn.close()
                await pooled.conn.wait_closed()

    async def close_all(self) -> None:
        for host_id in list(self._pool):
            await self.evict(host_id)


_pool: SshConnectionPool | None = None


def get_ssh_pool() -> SshConnectionPool:
    global _pool
    if _pool is None:
        _pool = SshConnectionPool()
    return _pool


def reset_ssh_pool_for_tests() -> None:
    """Test helper: drop the singleton so a fresh test gets a pool bound to
    its own event loop instead of one left over from a prior test's loop."""
    global _pool
    _pool = None
