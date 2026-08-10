"""Async SQLAlchemy engine/session setup.

Engine and session factory are built lazily (and cached) rather than at
import time, so tests can swap DB_PATH via get_settings.cache_clear() +
reset_engine_cache() and get a genuinely fresh engine per test run.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.db_url, echo=False, future=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)


def reset_engine_cache() -> None:
    """Test helper: force get_engine()/get_session_factory() to rebuild from
    (possibly changed) settings on next call."""
    get_engine.cache_clear()
    get_session_factory.cache_clear()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session
