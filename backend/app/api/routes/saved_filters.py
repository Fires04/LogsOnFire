"""A user's saved grep expressions — personal convenience data (like a
browser bookmark), not an admin-gated resource, so these routes just
require being logged in (get_current_user) rather than a specific
permission: any user manages only their own saved filters, scoped by
user_id on every query below.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.saved_filter import SavedFilter
from app.models.user import User
from app.schemas.saved_filter import SavedFilterCreate, SavedFilterOut
from app.security.deps import get_current_user

router = APIRouter(prefix="/api/saved-filters", tags=["saved-filters"])


@router.get("", response_model=list[SavedFilterOut])
async def list_saved_filters(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[SavedFilterOut]:
    result = await db.execute(select(SavedFilter).where(SavedFilter.user_id == user.id).order_by(SavedFilter.label))
    return list(result.scalars())


@router.post("", response_model=SavedFilterOut, status_code=status.HTTP_201_CREATED)
async def create_saved_filter(
    payload: SavedFilterCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SavedFilterOut:
    saved = SavedFilter(user_id=user.id, label=payload.label, expression=payload.expression)
    db.add(saved)
    await db.commit()
    await db.refresh(saved)
    return saved


@router.delete("/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_filter(
    filter_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    result = await db.execute(
        select(SavedFilter).where(SavedFilter.id == filter_id, SavedFilter.user_id == user.id)
    )
    saved = result.scalar_one_or_none()
    if saved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved filter not found")
    await db.delete(saved)
    await db.commit()
