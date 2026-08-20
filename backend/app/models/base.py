"""Shared model mixins."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """A DateTime that's always timezone-aware (UTC) coming back out of the
    ORM, regardless of dialect quirks. SQLite's DateTime type — even with
    timezone=True — never actually round-trips an offset: it formats/parses
    via a plain "%Y-%m-%d %H:%M:%S.%f" pattern with no timezone component,
    so a value written as a UTC-aware datetime comes back naive. Every
    datetime this app ever stores is UTC by convention (see utcnow() above),
    so re-attach that here rather than silently handing FastAPI a naive
    datetime — Pydantic serializes a naive datetime with no "Z"/offset
    suffix, which browsers parse as *local* time (e.g. dayjs()), making
    "last seen" clocks look hours off depending on the viewer's timezone.
    Found by direct testing: an agent connected seconds ago showed "last
    heartbeat: 2 hours ago" in a UTC+2 browser — exactly the local offset.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class UUIDPkMixin:
    id: Mapped[str] = mapped_column(primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
