from __future__ import annotations

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import record as audit_record
from app.core.rate_limit import limiter
from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, MeResponse
from app.security.deps import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    get_current_user,
    set_auth_cookies,
    user_is_admin,
)
from app.security.jwt import decode_token
from app.security.passwords import verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# A brute-force login attempt is the highest-value place to rate limit in
# this app — everything else sits behind an authenticated session already.
LOGIN_RATE_LIMIT = "10/minute"


@router.post("/login", response_model=MeResponse)
@limiter.limit(LOGIN_RATE_LIMIT)
async def login(
    request: Request, payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> MeResponse:
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.email == payload.email)
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        await audit_record(
            db, user_id=user.id if user else None, event_type="login_failed", detail={"email": payload.email}
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    set_auth_cookies(response, user.id, remember=payload.remember)
    await audit_record(db, user_id=user.id, event_type="login", detail={"remember": payload.remember})
    return MeResponse(id=user.id, email=user.email, is_admin=user_is_admin(user))


@router.post("/logout")
async def logout(response: Response) -> dict:
    clear_auth_cookies(response)
    return {"ok": True}


@router.post("/refresh", response_model=MeResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> MeResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")
    try:
        payload = decode_token(token, expected_type="refresh")
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token") from None

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == payload.get("sub"))
        .where(User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    # Roll the same "remember me" choice forward rather than silently
    # downgrading to the short-lived default on every refresh — it's
    # encoded in the refresh token's own payload (set_auth_cookies), not
    # tracked anywhere else.
    remember = bool(payload.get("remember", False))
    set_auth_cookies(response, user.id, remember=remember)
    return MeResponse(id=user.id, email=user.email, is_admin=user_is_admin(user))


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, is_admin=user_is_admin(user))
