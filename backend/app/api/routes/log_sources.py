from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import AgentOfflineError, AgentTimeoutError, get_agent_registry
from app.core.permissions import LOG_SOURCE_READ, LOG_SOURCE_WRITE
from app.database import get_db
from app.models.agent import Agent
from app.models.log_source import LogSource
from app.models.user import User
from app.schemas.log_source import (
    DockerContainersOut,
    JournalUnitsOut,
    LogSourceCreate,
    LogSourceOut,
    LogSourceUpdate,
    ResolveResponse,
    ResolvedFileOut,
)
from app.security.deps import require_permission

router = APIRouter(prefix="/api/agents", tags=["log-sources"])
# A second, non-agent-scoped router: standalone views like /view/log/:id only
# know the log source id (it's the whole point — one shareable link), so they
# need a way to look one up without already knowing which agent it belongs to.
global_router = APIRouter(prefix="/api/log-sources", tags=["log-sources"])


async def _get_agent_or_404(db: AsyncSession, agent_id: str) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


async def _get_log_source_or_404(db: AsyncSession, agent_id: str, log_source_id: str) -> LogSource:
    result = await db.execute(
        select(LogSource).where(LogSource.id == log_source_id, LogSource.agent_id == agent_id)
    )
    log_source = result.scalar_one_or_none()
    if log_source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Log source not found")
    return log_source


async def _resolve_via_agent(agent_id: str, mode: str, path_or_pattern: str, regex_base_dir: str | None) -> ResolveResponse:
    try:
        reply = await get_agent_registry().request(
            agent_id,
            {
                "type": "resolve",
                "log_source": {"mode": mode, "path_or_pattern": path_or_pattern, "regex_base_dir": regex_base_dir},
            },
        )
    except AgentOfflineError:
        return ResolveResponse(files=[], truncated=False, error="Agent is offline.")
    except AgentTimeoutError:
        return ResolveResponse(files=[], truncated=False, error="Agent did not respond in time.")

    if reply.get("error"):
        return ResolveResponse(files=[], truncated=False, error=reply["error"])
    return ResolveResponse(
        files=[ResolvedFileOut(**f) for f in reply.get("files", [])],
        truncated=reply.get("truncated", False),
        warning=reply.get("warning"),
    )


@router.get("/{agent_id}/log-sources", response_model=list[LogSourceOut])
async def list_log_sources(
    agent_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(LOG_SOURCE_READ))
) -> list[LogSourceOut]:
    await _get_agent_or_404(db, agent_id)
    result = await db.execute(select(LogSource).where(LogSource.agent_id == agent_id).order_by(LogSource.label))
    return list(result.scalars())


@router.post("/{agent_id}/log-sources", response_model=LogSourceOut, status_code=status.HTTP_201_CREATED)
async def create_log_source(
    agent_id: str,
    payload: LogSourceCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_WRITE)),
) -> LogSourceOut:
    await _get_agent_or_404(db, agent_id)
    log_source = LogSource(agent_id=agent_id, **payload.model_dump())
    db.add(log_source)
    await db.commit()
    await db.refresh(log_source)
    return log_source


@router.patch("/{agent_id}/log-sources/{log_source_id}", response_model=LogSourceOut)
async def update_log_source(
    agent_id: str,
    log_source_id: str,
    payload: LogSourceUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_WRITE)),
) -> LogSourceOut:
    log_source = await _get_log_source_or_404(db, agent_id, log_source_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(log_source, field, value)
    await db.commit()
    await db.refresh(log_source)
    return log_source


@router.delete("/{agent_id}/log-sources/{log_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_log_source(
    agent_id: str,
    log_source_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_WRITE)),
) -> None:
    log_source = await _get_log_source_or_404(db, agent_id, log_source_id)
    await db.delete(log_source)
    await db.commit()


@router.post("/{agent_id}/log-sources/resolve-preview", response_model=ResolveResponse)
async def resolve_preview(
    agent_id: str,
    payload: LogSourceCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_READ)),
) -> ResolveResponse:
    """Resolve a not-yet-saved mode/pattern combination, so the form can show
    live matches while the user is still typing, before hitting save."""
    await _get_agent_or_404(db, agent_id)
    return await _resolve_via_agent(agent_id, payload.mode, payload.path_or_pattern, payload.regex_base_dir)


@router.get("/{agent_id}/journal-units", response_model=JournalUnitsOut)
async def list_journal_units(
    agent_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(LOG_SOURCE_READ))
) -> JournalUnitsOut:
    """Powers the journal-mode picker in the "Add log source" form — a
    best-effort suggestion list from the agent's own `systemctl
    list-units`, not validation; the form still accepts a typed-in unit
    name if this fails or the agent is offline."""
    await _get_agent_or_404(db, agent_id)
    try:
        reply = await get_agent_registry().request(agent_id, {"type": "list_units"})
    except AgentOfflineError:
        return JournalUnitsOut(units=[], error="Agent is offline.")
    except AgentTimeoutError:
        return JournalUnitsOut(units=[], error="Agent did not respond in time.")
    return JournalUnitsOut(units=reply.get("units", []), error=reply.get("error"))


@router.get("/{agent_id}/docker-containers", response_model=DockerContainersOut)
async def list_docker_containers(
    agent_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(LOG_SOURCE_READ))
) -> DockerContainersOut:
    """Same as list_journal_units above, for docker mode's container
    picker."""
    await _get_agent_or_404(db, agent_id)
    try:
        reply = await get_agent_registry().request(agent_id, {"type": "list_containers"})
    except AgentOfflineError:
        return DockerContainersOut(containers=[], error="Agent is offline.")
    except AgentTimeoutError:
        return DockerContainersOut(containers=[], error="Agent did not respond in time.")
    return DockerContainersOut(containers=reply.get("containers", []), error=reply.get("error"))


@global_router.get("/{log_source_id}", response_model=LogSourceOut)
async def get_log_source(
    log_source_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(LOG_SOURCE_READ))
) -> LogSourceOut:
    result = await db.execute(select(LogSource).where(LogSource.id == log_source_id))
    log_source = result.scalar_one_or_none()
    if log_source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Log source not found")
    return log_source


@router.post("/{agent_id}/log-sources/{log_source_id}/resolve", response_model=ResolveResponse)
async def resolve_log_source(
    agent_id: str,
    log_source_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_READ)),
) -> ResolveResponse:
    await _get_agent_or_404(db, agent_id)
    log_source = await _get_log_source_or_404(db, agent_id, log_source_id)
    return await _resolve_via_agent(agent_id, log_source.mode, log_source.path_or_pattern, log_source.regex_base_dir)
