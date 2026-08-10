"""Hosts and their (encrypted) connection credentials."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPkMixin


class Host(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "hosts"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)  # unused if connection_type == "local"
    port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)
    connection_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "local" | "ssh"
    ssh_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "password" | "private_key"
    # Trust-on-first-use SSH host key pinning: an OpenSSH known_hosts-format
    # line ("hostname keytype base64key") captured on first successful
    # connection. All later connections are verified strictly against it, so
    # a changed host key (server reimage, MITM) fails loudly instead of
    # silently connecting. Reset via POST /api/hosts/{id}/reset-trust.
    known_host_key: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    credential: Mapped["HostCredential | None"] = relationship(
        back_populates="host", uselist=False, cascade="all, delete-orphan"
    )
    log_sources: Mapped[list["LogSource"]] = relationship(  # noqa: F821
        back_populates="host", cascade="all, delete-orphan"
    )


class HostCredential(UUIDPkMixin, Base):
    __tablename__ = "host_credentials"

    host_id: Mapped[str] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), unique=True, nullable=False)
    encrypted_password: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_private_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_private_key_passphrase: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encryption_key_version: Mapped[int] = mapped_column(default=1, nullable=False)

    host: Mapped[Host] = relationship(back_populates="credential")
