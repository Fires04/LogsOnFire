"""A log source belongs to a host and is either an exact path, a glob pattern,
or a regex filter applied to a directory listing.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPkMixin


class LogSource(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "log_sources"

    host_id: Mapped[str] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # "exact_path" | "glob" | "regex"
    path_or_pattern: Mapped[str] = mapped_column(String(1000), nullable=False)
    # required when mode == "regex": the directory to list before filtering by regex
    regex_base_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    host: Mapped["Host"] = relationship(back_populates="log_sources")  # noqa: F821
