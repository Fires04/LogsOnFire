"""The agent-facing WebSocket endpoint: one persistent connection per
enrolled Agent, held open by the agent process itself (agent/), used as a
lightweight control channel (hello/ping-pong) and as the transport for
resolve/browse requests and start_tail/stop_tail-driven line streaming.
Separate module from ws_logs.py (browser-facing) — different auth model,
different message shapes, different lifecycle.

Agent -> server messages:
    {"type": "hello", "agent_version"}
    {"type": "resolve_result", "req_id", "files", "truncated", "error"?, "warning"?}
    {"type": "browse_result", "req_id", "path", "parent", "entries", "truncated", "error"?}
    {"type": "tail_backfill", "req_id", "lines", "error"?}   # reply to this connection's start_tail
    {"type": "tail_line", "resolved_path", "text"}
    {"type": "tail_error", "resolved_path", "message"}
    {"type": "tail_closed", "resolved_path", "reason"}
    {"type": "pong"}

Server -> agent messages:
    {"type": "resolve", "req_id", "log_source": {mode, path_or_pattern, regex_base_dir}}
    {"type": "browse", "req_id", "path"?}
    {"type": "start_tail", "req_id", "resolved_path"}
    {"type": "stop_tail", "resolved_path"}
    {"type": "ping"}

Auth: `Authorization: Bearer <token>` header at WS handshake — non-browser
traffic, no cookie/CSRF surface, so unlike /ws/logs this never touches
CsrfMiddleware (which only wraps HTTP request/response cycles, not
WebSocket handshakes, for either endpoint).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.heartbeat import HeartbeatMonitor, HeartbeatTimeout
from app.agents.registry import get_agent_registry
from app.agents.service import mark_connected, mark_disconnected, mark_heartbeat
from app.database import get_db
from app.models.agent import Agent
from app.security.agent_tokens import hash_token
from app.tailing.manager import get_tail_manager

router = APIRouter(tags=["ws-agent"])
logger = logging.getLogger("logsonfire.ws_agent")


async def _authenticate(websocket: WebSocket, db: AsyncSession) -> Agent | None:
    auth_header = websocket.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    if not token:
        return None
    result = await db.execute(select(Agent).where(Agent.token_hash == hash_token(token)))
    return result.scalar_one_or_none()


@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket, db: AsyncSession = Depends(get_db)) -> None:
    agent = await _authenticate(websocket, db)
    if agent is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    registry = get_agent_registry()
    manager = get_tail_manager()
    registry.attach(agent.id, websocket)
    await mark_connected(db, agent, agent_version=None)
    logger.info("agent %s (%s) connected", agent.id, agent.name)

    monitor = HeartbeatMonitor(websocket)

    async def read_loop() -> None:
        while True:
            raw: dict[str, Any] = await websocket.receive_json()
            msg_type = raw.get("type")

            if msg_type == "hello":
                agent.agent_version = raw.get("agent_version")
                await db.commit()
            elif msg_type == "pong":
                rtt_ms = monitor.notify_pong()
                await mark_heartbeat(db, agent, rtt_ms)
            elif msg_type in ("resolve_result", "browse_result", "tail_backfill"):
                req_id = raw.get("req_id")
                if req_id:
                    registry.deliver(agent.id, req_id, raw)
            elif msg_type == "tail_line":
                session = manager.get_session(agent.id, raw.get("resolved_path", ""))
                if session is not None:
                    session.receive_line(raw.get("text", ""))
            elif msg_type == "tail_error":
                session = manager.get_session(agent.id, raw.get("resolved_path", ""))
                if session is not None:
                    session.receive_error(raw.get("message", "unknown error"))
            elif msg_type == "tail_closed":
                session = manager.get_session(agent.id, raw.get("resolved_path", ""))
                if session is not None:
                    session.receive_closed(raw.get("reason", "stopped"))
            else:
                logger.warning("agent %s sent unknown message type: %r", agent.id, msg_type)

    read_task = asyncio.create_task(read_loop(), name=f"ws-agent-read:{agent.id}")
    heartbeat_task = asyncio.create_task(monitor.run(), name=f"ws-agent-heartbeat:{agent.id}")

    try:
        done, pending = await asyncio.wait({read_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            exc = task.exception()
            if isinstance(exc, HeartbeatTimeout):
                logger.info("agent %s heartbeat timed out — closing", agent.id)
                with contextlib.suppress(Exception):
                    await websocket.close(code=1001)
            elif exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning("agent %s connection ended with error: %s", agent.id, exc)
    finally:
        await mark_disconnected(db, agent)
        logger.info("agent %s (%s) disconnected", agent.id, agent.name)
