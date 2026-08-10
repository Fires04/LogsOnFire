from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permissions import LOG_SOURCE_READ, LOG_SOURCE_WRITE
from app.database import get_db
from app.models.host import Host
from app.models.log_source import LogSource
from app.models.user import User
from app.providers.registry import get_provider
from app.schemas.log_source import LogSourceCreate, LogSourceOut, LogSourceUpdate, ResolveResponse, ResolvedFileOut
from app.security.deps import require_permission

router = APIRouter(prefix="/api/hosts", tags=["log-sources"])
# A second, non-host-scoped router: standalone views like /view/log/:id only
# know the log source id (it's the whole point — one shareable link), so they
# need a way to look one up without already knowing which host it belongs to.
global_router = APIRouter(prefix="/api/log-sources", tags=["log-sources"])


async def _get_host_or_404(db: AsyncSession, host_id: str) -> Host:
    result = await db.execute(
        select(Host).options(selectinload(Host.credential)).where(Host.id == host_id)
    )
    host = result.scalar_one_or_none()
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Host not found")
    return host


async def _get_log_source_or_404(db: AsyncSession, host_id: str, log_source_id: str) -> LogSource:
    result = await db.execute(
        select(LogSource).where(LogSource.id == log_source_id, LogSource.host_id == host_id)
    )
    log_source = result.scalar_one_or_none()
    if log_source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Log source not found")
    return log_source


@router.get("/{host_id}/log-sources", response_model=list[LogSourceOut])
async def list_log_sources(
    host_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(LOG_SOURCE_READ))
) -> list[LogSourceOut]:
    await _get_host_or_404(db, host_id)
    result = await db.execute(select(LogSource).where(LogSource.host_id == host_id).order_by(LogSource.label))
    return list(result.scalars())


@router.post("/{host_id}/log-sources", response_model=LogSourceOut, status_code=status.HTTP_201_CREATED)
async def create_log_source(
    host_id: str,
    payload: LogSourceCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_WRITE)),
) -> LogSourceOut:
    await _get_host_or_404(db, host_id)
    log_source = LogSource(host_id=host_id, **payload.model_dump())
    db.add(log_source)
    await db.commit()
    await db.refresh(log_source)
    return log_source


@router.patch("/{host_id}/log-sources/{log_source_id}", response_model=LogSourceOut)
async def update_log_source(
    host_id: str,
    log_source_id: str,
    payload: LogSourceUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_WRITE)),
) -> LogSourceOut:
    log_source = await _get_log_source_or_404(db, host_id, log_source_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(log_source, field, value)
    await db.commit()
    await db.refresh(log_source)
    return log_source


@router.delete("/{host_id}/log-sources/{log_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_log_source(
    host_id: str,
    log_source_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_WRITE)),
) -> None:
    log_source = await _get_log_source_or_404(db, host_id, log_source_id)
    await db.delete(log_source)
    await db.commit()


@router.post("/{host_id}/log-sources/resolve-preview", response_model=ResolveResponse)
async def resolve_preview(
    host_id: str,
    payload: LogSourceCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_READ)),
) -> ResolveResponse:
    """Resolve a not-yet-saved mode/pattern combination, so the form can show
    live matches while the user is still typing, before hitting save."""
    host = await _get_host_or_404(db, host_id)
    draft = LogSource(host_id=host_id, **payload.model_dump())

    provider = get_provider(host)
    try:
        files, truncated = await provider.resolve_sources(draft)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a 500
        return ResolveResponse(files=[], truncated=False, error=str(exc))

    warning = next((f.warning for f in files if f.warning), None)
    return ResolveResponse(
        files=[ResolvedFileOut(path=f.path, size=f.size, mtime=f.mtime) for f in files],
        truncated=truncated,
        warning=warning,
    )


@global_router.get("/{log_source_id}", response_model=LogSourceOut)
async def get_log_source(
    log_source_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(LOG_SOURCE_READ))
) -> LogSourceOut:
    result = await db.execute(select(LogSource).where(LogSource.id == log_source_id))
    log_source = result.scalar_one_or_none()
    if log_source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Log source not found")
    return log_source


@router.post("/{host_id}/log-sources/{log_source_id}/resolve", response_model=ResolveResponse)
async def resolve_log_source(
    host_id: str,
    log_source_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(LOG_SOURCE_READ)),
) -> ResolveResponse:
    host = await _get_host_or_404(db, host_id)
    log_source = await _get_log_source_or_404(db, host_id, log_source_id)

    provider = get_provider(host)
    try:
        files, truncated = await provider.resolve_sources(log_source)
    except ValueError as exc:
        return ResolveResponse(files=[], truncated=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a resolve error, not a 500
        return ResolveResponse(files=[], truncated=False, error=str(exc))

    warning = next((f.warning for f in files if f.warning), None)
    return ResolveResponse(
        files=[ResolvedFileOut(path=f.path, size=f.size, mtime=f.mtime) for f in files],
        truncated=truncated,
        warning=warning,
    )
