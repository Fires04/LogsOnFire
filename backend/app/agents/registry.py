"""AgentConnectionRegistry: the live half of the Agent Manager.

Holds exactly one open WebSocket per connected agent, plus request/reply
matching for messages that need a response (resolve, browse, start_tail's
backfill) sent down that same persistent connection. This is the server-side
mirror of what frontend/src/lib/wsClient.ts already does client-side for
/ws/logs (a pendingByReqId-style Future registry over one multiplexed
socket) — same pattern, agent-facing instead of browser-facing.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.config import get_settings

logger = logging.getLogger("logsonfire.agents.registry")


class AgentOfflineError(Exception):
    """Raised when a request targets an agent with no live connection."""


class AgentTimeoutError(Exception):
    """Raised when a connected agent didn't reply to a request in time."""


@dataclass
class _Connection:
    websocket: WebSocket
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


class AgentConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, _Connection] = {}

    def attach(self, agent_id: str, websocket: WebSocket) -> None:
        self._connections[agent_id] = _Connection(websocket=websocket)

    def detach(self, agent_id: str) -> None:
        conn = self._connections.pop(agent_id, None)
        if conn is None:
            return
        for fut in conn.pending.values():
            if not fut.done():
                fut.set_exception(AgentOfflineError("agent disconnected"))

    def is_connected(self, agent_id: str) -> bool:
        return agent_id in self._connections

    async def send(self, agent_id: str, message: dict) -> None:
        conn = self._connections.get(agent_id)
        if conn is None:
            raise AgentOfflineError(f"agent {agent_id} is not connected")
        await conn.websocket.send_json(message)

    async def request(self, agent_id: str, message: dict, timeout: float | None = None) -> dict:
        """Send `message` (must not already carry req_id) down the agent's
        connection and await the matching reply, delivered via
        resolve_reply()/deliver() when ws_agent.py's dispatcher sees a
        message carrying the same req_id come back in.
        """
        conn = self._connections.get(agent_id)
        if conn is None:
            raise AgentOfflineError(f"agent {agent_id} is not connected")

        req_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        conn.pending[req_id] = fut
        try:
            await conn.websocket.send_json({**message, "req_id": req_id})
            timeout = timeout if timeout is not None else get_settings().agent_request_timeout_seconds
            try:
                return await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                raise AgentTimeoutError(f"agent {agent_id} did not respond in time") from None
        finally:
            conn.pending.pop(req_id, None)

    def deliver(self, agent_id: str, req_id: str, payload: dict) -> bool:
        """Called by ws_agent.py when a reply (resolve_result/browse_result/
        tail_backfill) arrives. Returns True if it matched a pending
        request, False if it was unsolicited/stale (e.g. arrived after the
        requester already timed out — just logged, not an error)."""
        conn = self._connections.get(agent_id)
        if conn is None:
            return False
        fut = conn.pending.get(req_id)
        if fut is None or fut.done():
            return False
        fut.set_result(payload)
        return True


_registry: AgentConnectionRegistry | None = None


def get_agent_registry() -> AgentConnectionRegistry:
    global _registry
    if _registry is None:
        _registry = AgentConnectionRegistry()
    return _registry


def reset_agent_registry_for_tests() -> None:
    global _registry
    _registry = None
