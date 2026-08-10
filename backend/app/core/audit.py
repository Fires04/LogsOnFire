"""Audit trail helper — a lightweight, high-value addition for a tool that
stores SSH credentials and connects to production servers: who logged in,
who added/changed/removed which host, and when a tail session against a
given host started.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record(
    db: AsyncSession,
    *,
    user_id: str | None,
    event_type: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
    )
    await db.commit()
