"""Persistent WebSocket connection to the server, with automatic
reconnect+backoff mirroring frontend/src/lib/wsClient.ts's pattern (base
delay 500ms, capped at 15s, doubling). The agent is stateless across a
reconnect — it doesn't remember what it was tailing; the server is the
source of truth for "what should currently be running" and re-sends
start_tail for anything that still has a subscriber once hello arrives.
"""
from __future__ import annotations

import asyncio
import json
import logging

import websockets

from logsonfire_agent.config import AgentConfig
from logsonfire_agent.dispatch import Dispatcher

logger = logging.getLogger("logsonfire_agent.wsclient")

RECONNECT_BASE_DELAY = 0.5
RECONNECT_MAX_DELAY = 15.0


async def run(config: AgentConfig) -> None:
    """Runs forever, reconnecting on any failure, until cancelled."""
    delay = RECONNECT_BASE_DELAY
    while True:
        try:
            await _connect_once(config)
            delay = RECONNECT_BASE_DELAY  # a clean session (however brief) resets backoff
            logger.info("disconnected from %s — reconnecting in %.1fs", config.server_url, delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - log and retry, an agent must never crash out
            logger.warning("connection to %s failed: %s — retrying in %.1fs", config.server_url, exc, delay)

        await asyncio.sleep(delay)
        delay = min(delay * 2, RECONNECT_MAX_DELAY)


async def _connect_once(config: AgentConfig) -> None:
    headers = {"Authorization": f"Bearer {config.token}"}
    async with websockets.connect(config.ws_url, additional_headers=headers, ping_interval=None) as ws:
        # ping_interval=None: the *server* drives heartbeats (app/agents/
        # heartbeat.py sends its own {"type": "ping"} on a schedule and we
        # reply {"type": "pong"} below) — a second, independent protocol-level
        # ping from the websockets library underneath would be redundant.
        logger.info("connected to %s", config.server_url)

        async def send(message: dict) -> None:
            await ws.send(json.dumps(message))

        dispatcher = Dispatcher(send)
        await send({"type": "hello", "agent_version": config.agent_version})
        try:
            async for raw in ws:
                message = json.loads(raw)
                if message.get("type") == "ping":
                    await send({"type": "pong"})
                    continue
                await dispatcher.handle(message)
        finally:
            await dispatcher.stop_all()
