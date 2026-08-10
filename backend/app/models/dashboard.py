"""Dashboards: saved layouts of log panels, possibly spanning multiple hosts."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPkMixin


class Dashboard(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "dashboards"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    panels: Mapped[list["DashboardPanel"]] = relationship(
        back_populates="dashboard", cascade="all, delete-orphan", order_by="DashboardPanel.display_order"
    )


class DashboardPanel(UUIDPkMixin, Base):
    __tablename__ = "dashboard_panels"

    dashboard_id: Mapped[str] = mapped_column(ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=False)
    log_source_id: Mapped[str] = mapped_column(ForeignKey("log_sources.id", ondelete="CASCADE"), nullable=False)
    # Snapshot of which concrete file this panel points at, for pattern-based log sources.
    resolved_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    position_x: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position_y: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    dashboard: Mapped[Dashboard] = relationship(back_populates="panels")
