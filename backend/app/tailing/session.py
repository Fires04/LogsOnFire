"""A TailSession owns exactly one real 'follow this file' operation on the
owning agent — a start_tail/stop_tail pair sent down that agent's
/ws/agent connection — no matter how many browser WebSocket subscribers are
watching it here on the server (that de-duplication lives in
tailing/manager.py). It keeps a bounded ring buffer of recent lines, used
both as backfill context for newly-attached subscribers and as the corpus
the grep bar searches.
"""
from __future__ import annotations

import logging
from collections import deque

from app.agents.registry import get_agent_registry
from app.config import get_settings
from app.tailing.broker import LineBroker, TailClosed, TailError, TailLine

logger = logging.getLogger("logsonfire.tailing.session")


class TailSession:
    def __init__(self, key: str, agent_id: str, path: str) -> None:
        self.key = key
        self.agent_id = agent_id
        self.path = path
        self.broker = LineBroker()

        settings = get_settings()
        self.buffer: deque[str] = deque(maxlen=settings.log_buffer_max_lines)
        self.subscriber_count = 0
        self.status = "starting"  # starting | running | error | closed
        self.error_message: str | None = None

    async def start(self) -> None:
        """Ask the owning agent to start tailing this path (start_tail) and
        load the initial backfill it sends back. Raises on failure (agent
        offline, agent-reported resolve/open error, request timeout) — the
        caller (tailing/manager.py) is expected to not register a session
        that failed to start.
        """
        registry = get_agent_registry()
        reply = await registry.request(self.agent_id, {"type": "start_tail", "resolved_path": self.path})
        error = reply.get("error")
        if error:
            self.status = "error"
            self.error_message = error
            raise RuntimeError(error)
        self.buffer.extend(reply.get("lines", []))
        self.status = "running"

    def receive_line(self, text: str) -> None:
        self.buffer.append(text)
        self.broker.publish(TailLine(text))

    def receive_error(self, message: str) -> None:
        self.status = "error"
        self.error_message = message
        self.broker.publish(TailError(message))

    def receive_closed(self, reason: str) -> None:
        """Called either when the agent itself reports tail_closed, or by
        agents/service.py's disconnect handler sweeping every session owned
        by an agent that just dropped off (reason="agent_disconnected")."""
        self.status = "closed"
        self.broker.publish(TailClosed(reason))

    async def stop(self) -> None:
        """Server-initiated stop (last browser subscriber went away). Tells
        the agent to stop_tail — best-effort, the agent may already be
        disconnected, in which case there's nothing to tell it."""
        self.status = "closed"
        registry = get_agent_registry()
        try:
            await registry.send(self.agent_id, {"type": "stop_tail", "resolved_path": self.path})
        except Exception:
            logger.debug("could not send stop_tail for %s (agent likely disconnected)", self.key)
