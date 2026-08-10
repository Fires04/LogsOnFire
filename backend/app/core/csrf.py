"""Double-submit-cookie CSRF protection for cookie-authenticated mutating requests."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.security.deps import CSRF_COOKIE, CSRF_HEADER

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
# Login has no CSRF cookie yet (pre-authentication); it's protected instead by
# SameSite=Lax cookies plus not being a state-read endpoint an attacker gains from.
EXEMPT_PATHS = {"/api/auth/login"}


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        needs_check = (
            request.method not in SAFE_METHODS
            and request.url.path not in EXEMPT_PATHS
            and request.url.path.startswith("/api")
        )
        if needs_check:
            cookie_token = request.cookies.get(CSRF_COOKIE)
            header_token = request.headers.get(CSRF_HEADER)
            if not cookie_token or not header_token or cookie_token != header_token:
                return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
        return await call_next(request)
