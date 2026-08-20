from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.install_links import get_install_link_store
from app.agents.install_links import LINK_TTL_SECONDS
from app.agents.registry import AgentOfflineError, AgentTimeoutError, get_agent_registry
from app.agents.service import enroll_agent, reissue_token as reissue_token_service
from app.core.audit import record as audit_record
from app.core.permissions import AGENT_READ, AGENT_WRITE
from app.database import get_db
from app.models.agent import Agent
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentCreateResult, AgentOut, AgentUpdate, InstallLinkCreate, InstallLinkOut
from app.schemas.browse import BrowseResponse, DirEntryOut
from app.security.deps import require_permission

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _to_out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        name=agent.name,
        online=agent.online,
        last_seen_at=agent.last_seen_at,
        last_heartbeat_rtt_ms=agent.last_heartbeat_rtt_ms,
        agent_version=agent.agent_version,
        token_prefix=agent.token_prefix,
    )


async def _get_agent_or_404(db: AsyncSession, agent_id: str) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


@router.get("", response_model=list[AgentOut])
async def list_agents(
    db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(AGENT_READ))
) -> list[AgentOut]:
    result = await db.execute(select(Agent).order_by(Agent.name))
    return [_to_out(a) for a in result.scalars()]


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(AGENT_READ))
) -> AgentOut:
    return _to_out(await _get_agent_or_404(db, agent_id))


@router.post("", response_model=AgentCreateResult, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(AGENT_WRITE)),
) -> AgentCreateResult:
    agent, token = await enroll_agent(db, payload.name, user.id)
    await audit_record(
        db, user_id=user.id, event_type="agent_created", target_type="agent", target_id=agent.id,
        detail={"name": agent.name},
    )
    return AgentCreateResult(agent=_to_out(agent), token=token)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(AGENT_WRITE)),
) -> AgentOut:
    agent = await _get_agent_or_404(db, agent_id)
    if payload.name is not None:
        agent.name = payload.name
    await db.commit()
    await audit_record(db, user_id=user.id, event_type="agent_updated", target_type="agent", target_id=agent_id)
    return _to_out(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_permission(AGENT_WRITE))
) -> None:
    agent = await _get_agent_or_404(db, agent_id)
    name = agent.name
    await db.delete(agent)
    await db.commit()
    await audit_record(
        db, user_id=user.id, event_type="agent_deleted", target_type="agent", target_id=agent_id, detail={"name": name}
    )


@router.post("/{agent_id}/reissue-token", response_model=AgentCreateResult)
async def reissue_token(
    agent_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_permission(AGENT_WRITE))
) -> AgentCreateResult:
    """Rotates the agent's bearer token and force-disconnects its current
    live connection, if any — a compromised token can't keep an existing
    session alive after rotation."""
    agent = await _get_agent_or_404(db, agent_id)
    token = await reissue_token_service(db, agent)
    await audit_record(db, user_id=user.id, event_type="agent_token_reissued", target_type="agent", target_id=agent_id)
    return AgentCreateResult(agent=_to_out(agent), token=token)


@router.post("/{agent_id}/install-link", response_model=InstallLinkOut)
async def create_install_link(
    agent_id: str,
    payload: InstallLinkCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(AGENT_WRITE)),
) -> InstallLinkOut:
    """Generates a one-time `GET /agent/install/{code}` download link with
    --server/--token already baked in, so `curl ... | sudo bash` needs no
    arguments at all — the real bearer token never has to appear in a shell
    history or a `ps` listing on the host being enrolled. The token is
    taken from the request body (this endpoint's caller, i.e. the browser
    that just received it from create_agent/reissue_token) rather than the
    database, since the server never stores it in plaintext anywhere.
    """
    await _get_agent_or_404(db, agent_id)  # 404s cleanly if the id is bogus
    if not payload.is_valid_scheme:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "server_url must start with ws:// or wss://")
    code = get_install_link_store().create(agent_id, payload.token, payload.server_url)
    return InstallLinkOut(code=code, expires_in_seconds=LINK_TTL_SECONDS)


@router.get("/{agent_id}/browse", response_model=BrowseResponse)
async def browse_agent(
    agent_id: str,
    path: str | None = Query(None, description="Directory to list; omit for the agent's default root"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(AGENT_READ)),
) -> BrowseResponse:
    """Powers the log-source file picker: asks the connected agent to list
    one directory on its own host, over the persistent /ws/agent connection.
    """
    agent = await _get_agent_or_404(db, agent_id)
    try:
        reply = await get_agent_registry().request(agent.id, {"type": "browse", "path": path})
    except AgentOfflineError:
        return BrowseResponse(path=path or "/", parent=None, entries=[], truncated=False, error="Agent is offline.")
    except AgentTimeoutError:
        return BrowseResponse(
            path=path or "/", parent=None, entries=[], truncated=False, error="Agent did not respond in time."
        )

    if reply.get("error"):
        return BrowseResponse(
            path=reply.get("path") or path or "/", parent=reply.get("parent"), entries=[], truncated=False,
            error=reply["error"],
        )
    return BrowseResponse(
        path=reply["path"],
        parent=reply.get("parent"),
        entries=[DirEntryOut(**e) for e in reply.get("entries", [])],
        truncated=reply.get("truncated", False),
    )
