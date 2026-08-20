"""Per-connection heartbeat: periodically ping a connected agent and detect
one that's gone quiet, so `Agent.connected_at`/`online` in the UI reflects
reality rather than just "TCP hasn't dropped yet" (a half-open connection
can look alive for a long time otherwise).
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import WebSocket

from app.config import get_settings

logger = logging.getLogger("logsonfire.agents.heartbeat")


class HeartbeatTimeout(Exception):
    """Raised into the caller when an agent misses too many pongs in a row."""


class HeartbeatMonitor:
    """One instance per live /ws/agent connection. `notify_pong()` is called
    by ws_agent.py's message dispatcher whenever a `pong` arrives; `run()`
    is the background loop that pings on an interval and raises
    HeartbeatTimeout if too much time passes without a pong.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._last_pong = time.monotonic()
        # When the most recent ping was actually sent — None until run()
        # sends its first one. Used to compute a real round-trip time in
        # notify_pong(); measuring against _last_pong instead (as an
        # earlier version of this did) mixes up "time since the previous
        # pong" (~= the heartbeat interval, e.g. 30000ms) with the actual
        # network RTT (typically single-digit milliseconds) — found by
        # direct testing, the UI showed a suspiciously round "30002 ms" RTT
        # for a connection on localhost.
        self._last_ping_sent: float | None = None

    def notify_pong(self) -> float:
        """Returns the round-trip time in ms: time from the most recently
        sent ping to this pong. 0 if a pong arrives before any ping was
        sent by this monitor (shouldn't normally happen)."""
        now = time.monotonic()
        self._last_pong = now
        rtt_ms = (now - self._last_ping_sent) * 1000 if self._last_ping_sent is not None else 0.0
        return rtt_ms

    async def run(self) -> None:
        settings = get_settings()
        interval = settings.agent_heartbeat_interval_seconds
        timeout = settings.agent_heartbeat_timeout_seconds
        while True:
            await asyncio.sleep(interval)
            if time.monotonic() - self._last_pong > timeout:
                raise HeartbeatTimeout(f"no pong received in over {timeout}s")
            self._last_ping_sent = time.monotonic()
            await self._websocket.send_json({"type": "ping"})
