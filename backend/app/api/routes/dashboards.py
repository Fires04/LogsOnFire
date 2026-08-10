from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permissions import DASHBOARD_READ, DASHBOARD_WRITE
from app.database import get_db
from app.models.dashboard import Dashboard, DashboardPanel
from app.models.user import User
from app.schemas.dashboard import DashboardCreate, DashboardOut, DashboardUpdate
from app.security.deps import require_permission

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])


async def _get_dashboard_or_404(db: AsyncSession, dashboard_id: str) -> Dashboard:
    result = await db.execute(
        select(Dashboard).options(selectinload(Dashboard.panels)).where(Dashboard.id == dashboard_id)
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard not found")
    return dashboard


@router.get("", response_model=list[DashboardOut])
async def list_dashboards(
    db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(DASHBOARD_READ))
) -> list[DashboardOut]:
    # Dashboards are shared across all users of the instance (single-team
    # monitoring tool) rather than private per-owner — owner_id is kept for
    # display/audit ("created by") and future per-dashboard ACLs.
    result = await db.execute(select(Dashboard).options(selectinload(Dashboard.panels)).order_by(Dashboard.name))
    return list(result.scalars())


@router.post("", response_model=DashboardOut, status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    payload: DashboardCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(DASHBOARD_WRITE)),
) -> DashboardOut:
    dashboard = Dashboard(name=payload.name, owner_id=user.id)
    dashboard.panels = [DashboardPanel(**p.model_dump()) for p in payload.panels]
    db.add(dashboard)
    await db.commit()
    return await _get_dashboard_or_404(db, dashboard.id)


@router.get("/{dashboard_id}", response_model=DashboardOut)
async def get_dashboard(
    dashboard_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(DASHBOARD_READ))
) -> DashboardOut:
    return await _get_dashboard_or_404(db, dashboard_id)


@router.patch("/{dashboard_id}", response_model=DashboardOut)
async def update_dashboard(
    dashboard_id: str,
    payload: DashboardUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(DASHBOARD_WRITE)),
) -> DashboardOut:
    dashboard = await _get_dashboard_or_404(db, dashboard_id)
    if payload.name is not None:
        dashboard.name = payload.name
    if payload.panels is not None:
        # Simplest correct approach for a small admin tool: replace the whole
        # panel set rather than diffing individual panels.
        dashboard.panels = [DashboardPanel(**p.model_dump()) for p in payload.panels]
    await db.commit()
    return await _get_dashboard_or_404(db, dashboard_id)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(DASHBOARD_WRITE))
) -> None:
    dashboard = await _get_dashboard_or_404(db, dashboard_id)
    await db.delete(dashboard)
    await db.commit()
