"""High-level Agent Manager operations, kept out of ws_agent.py (which stays
a thin (de)serialization layer) and out of api/routes/agents.py (which stays
a thin REST layer) — the same "route handler is glue, logic lives beside it"
split tailing/manager.py already has from ws_logs.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import get_agent_registry
from app.models.agent import Agent
from app.security.agent_tokens import generate_token, hash_token, token_prefix
from app.tailing.manager import get_tail_manager


async def enroll_agent(db: AsyncSession, name: str, created_by: str) -> tuple[Agent, str]:
    """Creates a new Agent and returns (agent, plaintext_token). The token
    is never stored or logged in plaintext anywhere — this is the only
    moment it exists outside the agent's own config file."""
    token = generate_token()
    agent = Agent(
        name=name,
        token_hash=hash_token(token),
        token_prefix=token_prefix(token),
        created_by=created_by,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent, token


async def reissue_token(db: AsyncSession, agent: Agent) -> str:
    """Rotates an agent's token and force-disconnects its current live
    connection (if any), so a compromised token can't keep an existing
    session alive after rotation."""
    token = generate_token()
    agent.token_hash = hash_token(token)
    agent.token_prefix = token_prefix(token)
    await db.commit()

    registry = get_agent_registry()
    if registry.is_connected(agent.id):
        try:
            await registry.send(agent.id, {"type": "error", "message": "token reissued — reconnect required"})
        except Exception:
            pass
        # The connection is force-closed by ws_agent.py's caller once this
        # returns; registry.detach() happens in its own disconnect handling.
    return token


async def mark_connected(db: AsyncSession, agent: Agent, agent_version: str | None) -> None:
    agent.connected_at = datetime.now(timezone.utc)
    agent.last_seen_at = agent.connected_at
    agent.agent_version = agent_version
    await db.commit()


async def mark_heartbeat(db: AsyncSession, agent: Agent, rtt_ms: float) -> None:
    agent.last_seen_at = datetime.now(timezone.utc)
    agent.last_heartbeat_rtt_ms = round(rtt_ms)
    await db.commit()


async def mark_disconnected(db: AsyncSession, agent: Agent) -> None:
    """Called from ws_agent.py's finally block on any disconnect (clean
    close, ping timeout, or a raw dropped TCP connection all end up here).
    Every TailSession this agent owned is marked closed so subscribed
    browsers see it immediately instead of hanging silently."""
    agent.connected_at = None
    agent.last_seen_at = datetime.now(timezone.utc)
    await db.commit()

    get_agent_registry().detach(agent.id)
    for session in get_tail_manager().sessions_for_agent(agent.id):
        session.receive_closed("agent_disconnected")
