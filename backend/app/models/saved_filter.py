"""A user's saved grep expression, reusable across any log panel — not tied
to a specific log source, since a filter like "-i error -C 3" is generally
useful on more than one log.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPkMixin


class SavedFilter(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "saved_filters"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    expression: Mapped[str] = mapped_column(String(500), nullable=False)
