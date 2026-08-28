from __future__ import annotations

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
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


# --- Optional Authentik/OIDC login (fireauth.oidc.OIDCClient) -------------
#
# Bolted onto the password login above as an *additional* path, never a
# replacement (a hard rule for every FireAuth-using app, per SHARED.md) —
# nothing above this comment changes shape or behavior depending on whether
# OIDC is configured. fireauth's own build_auth_router()/SessionAuth are
# deliberately not used: its canned OIDC callback sets the session identity
# straight to a raw OIDC string with no user-table lookup, which would
# bypass this app's Role/Permission/ResourceGrant RBAC entirely. So this app
# calls fireauth.oidc.OIDCClient directly and maps the result onto its own
# User table + set_auth_cookies (identical cookies the password path
# issues), keeping exactly one identity/session format regardless of login
# method.
#
# Lazily constructed + cached, like security/jwt.py's _resolve_secret() /
# security/agent_tokens.py's pepper handling — settings-derived module
# state in this codebase is always lazy with an explicit test-reset hook,
# never built eagerly at import time (tests changing AUTHENTIK_* env vars
# between runs would otherwise see a stale client).
_oidc_client = None
_oidc_client_initialized = False


def _get_oidc_client():
    global _oidc_client, _oidc_client_initialized
    if _oidc_client_initialized:
        return _oidc_client
    settings = get_settings()
    if settings.oidc_enabled:
        from fireauth.oidc import OIDCClient, OIDCConfig

        _oidc_client = OIDCClient(
            OIDCConfig(
                client_id=settings.oidc_client_id,
                client_secret=settings.oidc_client_secret,
                issuer=settings.oidc_issuer,
                redirect_uri=settings.oidc_redirect_uri,
            )
        )
    else:
        _oidc_client = None
    _oidc_client_initialized = True
    return _oidc_client


def reset_oidc_client_for_tests() -> None:
    global _oidc_client, _oidc_client_initialized
    _oidc_client = None
    _oidc_client_initialized = False


@router.get("/oidc/login")
async def oidc_login(request: Request):
    oidc = _get_oidc_client()
    if oidc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return await oidc.login_redirect(request)


@router.get("/oidc/callback")
async def oidc_callback(request: Request, db: AsyncSession = Depends(get_db)):
    oidc = _get_oidc_client()
    if oidc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    userinfo = await oidc.handle_callback(request)
    email = userinfo.get("email")
    user = None
    if email:
        result = await db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.email == email)
            .where(User.is_active.is_(True))
        )
        user = result.scalar_one_or_none()

    if user is None:
        # Deliberately no auto-provisioning: an Authentik identity only
        # signs in here if it already matches an existing active User row.
        # There's no user-management UI yet (USER_MANAGE permission exists,
        # unused) — auto-creating a roleless account would just be a
        # confusing dead end (logged in, 403 on every permission-gated
        # route), not a useful account.
        await audit_record(
            db, user_id=None, event_type="login_failed", detail={"method": "oidc", "email": email}
        )
        return RedirectResponse(url="/login?error=oidc_unmapped", status_code=status.HTTP_302_FOUND)

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    # OIDC logins are always "remembered" — Authentik already has its own
    # session lifetime, there's no separate "stay signed in" checkbox on
    # this path (matches fireauth's own build_auth_router() convention).
    set_auth_cookies(response, user.id, remember=True)
    await audit_record(db, user_id=user.id, event_type="login", detail={"method": "oidc"})
    return response
