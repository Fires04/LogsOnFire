"""Agents: push-model clients that run on each monitored host, authenticate
with a bearer token, and stream log lines to this server over /ws/agent.

Replaces the old Host + HostCredential (SSH-pull) models entirely.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UTCDateTime, UUIDPkMixin


class Agent(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Bearer token auth (see security/agent_tokens.py) — HMAC-SHA256 hash,
    # never the plaintext token. token_prefix is not secret, just enough of
    # the token to let an admin tell tokens apart in the UI ("which one is
    # this") without re-displaying the real thing.
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)

    # Connectivity: connected_at is not None IS the online/offline signal —
    # deliberately not a separate status enum, so there's nothing to drift
    # out of sync with the actual /ws/agent connection state.
    connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_heartbeat_rtt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(50), nullable=True)  # self-reported at "hello"

    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Free-text — "which rack/VM/role is this", not structured/filterable.
    # A real multi-tag system (own table, filter-by-tag UI) is a bigger
    # feature than what's needed yet; this covers the actual ask ("how do I
    # tell my agents apart") far more cheaply.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    log_sources: Mapped[list["LogSource"]] = relationship(  # noqa: F821
        back_populates="agent", cascade="all, delete-orphan"
    )

    @property
    def online(self) -> bool:
        return self.connected_at is not None
