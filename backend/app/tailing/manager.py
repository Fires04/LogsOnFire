"""De-duplicates tailing: if two WebSocket subscriptions (from one browser
tab's dashboard, or from two different users/tabs entirely) want the same
path on the same agent, they share a single TailSession — one start_tail
sent to that agent — instead of each triggering its own.
"""
from __future__ import annotations

import asyncio

from app.tailing.broker import TailEvent
from app.tailing.session import TailSession


class TailSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TailSession] = {}
        self._key_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _key(agent_id: str, path: str) -> str:
        return f"{agent_id}:{path}"

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._key_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._key_locks[key] = lock
        return lock

    async def subscribe(
        self, agent_id: str, path: str
    ) -> tuple[TailSession, "asyncio.Queue[TailEvent]", list[str]]:
        """Returns (session, queue, backfill_snapshot). Raises whatever
        session.start() raises if a brand-new session fails to start (e.g.
        agent offline). Caller MUST call unsubscribe(session, queue) exactly
        once when done, even if it stops consuming due to an error.
        """
        key = self._key(agent_id, path)
        async with self._lock_for(key):
            session = self._sessions.get(key)
            if session is None or session.status in ("closed", "error"):
                session = TailSession(key, agent_id, path)
                self._sessions[key] = session
                try:
                    await session.start()
                except Exception:
                    self._sessions.pop(key, None)
                    raise

            session.subscriber_count += 1
            # Subscribe and snapshot the buffer back-to-back with no `await`
            # in between, so no line can land in neither or both of them
            # (asyncio is cooperative — nothing else can run in that gap).
            queue = session.broker.subscribe()
            backfill = list(session.buffer)

        return session, queue, backfill

    async def unsubscribe(self, session: TailSession, queue: "asyncio.Queue[TailEvent]") -> None:
        session.broker.unsubscribe(queue)
        async with self._lock_for(session.key):
            session.subscriber_count = max(0, session.subscriber_count - 1)
            if session.subscriber_count == 0:
                await session.stop()
                if self._sessions.get(session.key) is session:
                    del self._sessions[session.key]

    def get_session(self, agent_id: str, path: str) -> TailSession | None:
        """Looked up by ws_agent.py's message dispatcher to route an
        inbound tail_line/tail_error/tail_closed to the right session."""
        return self._sessions.get(self._key(agent_id, path))

    def sessions_for_agent(self, agent_id: str) -> list[TailSession]:
        """Used by agents/service.py when an agent disconnects, to mark
        every session it owned as closed."""
        prefix = f"{agent_id}:"
        return [s for k, s in self._sessions.items() if k.startswith(prefix)]


_manager: TailSessionManager | None = None


def get_tail_manager() -> TailSessionManager:
    global _manager
    if _manager is None:
        _manager = TailSessionManager()
    return _manager


def reset_tail_manager_for_tests() -> None:
    """Test helper: drop the singleton so a fresh test gets a manager bound
    to its own event loop instead of one left over from a prior test's loop."""
    global _manager
    _manager = None
