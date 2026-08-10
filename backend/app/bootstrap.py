"""First-boot bootstrap: run migrations, then seed the admin role/user if the
users table is empty.
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.config import get_settings
from app.core.permissions import ADMIN_ROLE, ALL_PERMISSIONS
from app.database import get_session_factory
from app.models.user import Permission, Role, User
from app.security.passwords import hash_password

logger = logging.getLogger("logsonfire.bootstrap")

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(cfg, "head")


async def seed_admin() -> None:
    settings = get_settings()
    async with get_session_factory()() as db:
        result = await db.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # already seeded

        logger.info("No users found — seeding admin role/permissions/user")

        permissions = [Permission(code=code) for code in ALL_PERMISSIONS]
        db.add_all(permissions)

        admin_role = Role(name=ADMIN_ROLE, description="Full access to all resources")
        admin_role.permissions = permissions
        db.add(admin_role)

        password = settings.admin_password
        generated = False
        if not password:
            password = secrets.token_urlsafe(16)
            generated = True

        admin_user = User(
            email=settings.admin_email,
            password_hash=hash_password(password),
            is_active=True,
        )
        admin_user.roles = [admin_role]
        db.add(admin_user)

        await db.commit()

        if generated:
            logger.critical(
                "Seeded admin user %s with a GENERATED password (shown once): %s "
                "— log in and note it down; it is not stored anywhere in plaintext.",
                settings.admin_email,
                password,
            )
        else:
            logger.info("Seeded admin user %s from ADMIN_PASSWORD env var", settings.admin_email)


async def bootstrap() -> None:
    run_migrations()
    await seed_admin()
