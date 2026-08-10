"""Users, roles, permissions — schema is future-proofed for multi-user even though
only a single admin account is seeded today. See resource_grants for the hook
that lets per-host/per-log-source grants be added later without a schema rewrite.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPkMixin

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users")


class Role(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, back_populates="roles")


class Permission(UUIDPkMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # e.g. "host:read"
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    roles: Mapped[list[Role]] = relationship(secondary=role_permissions, back_populates="permissions")


class ResourceGrant(UUIDPkMixin, TimestampMixin, Base):
    """Future hook for per-resource ACLs (e.g. 'user X can view host Y's logs')
    without needing a schema migration when multi-user support is built out.
    Not enforced today beyond the admin role's implicit wildcard access.
    """

    __tablename__ = "resource_grants"

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'host' | 'log_source' | 'dashboard'
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # null = all resources of that type
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False)
