"""FastAPI dependencies for authentication and authorization."""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import jwt as pyjwt

from app.config import get_settings
from app.core.permissions import ADMIN_ROLE
from app.database import get_db
from app.models.user import ResourceGrant, User
from app.security.jwt import create_token, decode_token

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def set_auth_cookies(response: Response, user_id: str) -> None:
    """Issue fresh access/refresh/csrf cookies for a logged-in user."""
    settings = get_settings()
    secure = settings.is_production
    access_token = create_token(user_id, "access")
    refresh_token = create_token(user_id, "refresh")
    csrf_token = secrets.token_urlsafe(32)

    common = dict(
        httponly=True,
        secure=secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
    )
    response.set_cookie(ACCESS_COOKIE, access_token, max_age=settings.access_token_ttl_minutes * 60, **common)
    response.set_cookie(REFRESH_COOKIE, refresh_token, max_age=settings.refresh_token_ttl_days * 86400, **common)
    # CSRF cookie is intentionally NOT httponly — JS must be able to read it
    # to echo it back as a header (double-submit pattern).
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=False,
        secure=secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(token, expected_type="access")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from None
    except pyjwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None

    user_id = payload.get("sub")
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == user_id)
        .where(User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def user_is_admin(user: User) -> bool:
    return any(role.name == ADMIN_ROLE for role in user.roles)


async def has_permission(
    db: AsyncSession,
    user: User,
    code: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> bool:
    if user_is_admin(user):
        return True

    role_ids = [role.id for role in user.roles]
    stmt = select(ResourceGrant).where(ResourceGrant.permission_code.in_([code, "*"]))
    result = await db.execute(stmt)
    for grant in result.scalars():
        if grant.user_id and grant.user_id != user.id:
            continue
        if grant.role_id and grant.role_id not in role_ids:
            continue
        if not grant.user_id and not grant.role_id:
            continue
        if resource_type and grant.resource_type != resource_type:
            continue
        if grant.resource_id and resource_id and grant.resource_id != resource_id:
            continue
        return True
    return False


def require_permission(code: str):
    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not await has_permission(db, user, code):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return _dep
