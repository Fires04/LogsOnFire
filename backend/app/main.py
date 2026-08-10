"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import auth, dashboards, hosts, log_sources, ws_logs
from app.bootstrap import bootstrap
from app.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.logging import configure_logging
from app.core.rate_limit import limiter

logger = logging.getLogger("logsonfire")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("LogsOnFire starting up (env=%s)", get_settings().env)
    await bootstrap()
    yield
    logger.info("LogsOnFire shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LogsOnFire", lifespan=lifespan)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(InvalidTag)
    async def invalid_tag_handler(_request: Request, _exc: InvalidTag) -> JSONResponse:
        # Defense in depth: ssh/connect.py already turns this into a clean
        # SshAuthError for the normal host-connection path. This handler is
        # the safety net for any other place a stored secret gets decrypted,
        # so a MASTER_KEY mismatch never surfaces as a bare 500.
        logger.error("decryption failed with InvalidTag — MASTER_KEY likely does not match stored data")
        return JSONResponse(
            {"detail": "Could not decrypt stored credential — MASTER_KEY does not match. See README."},
            status_code=500,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        # Explicit catch-all so an unhandled exception always ends up with a
        # visible traceback in the server logs (relying on the ASGI server's
        # own default error logging was found to be unreliable in this
        # deployment) and a JSON body instead of Starlette's plain-text default.
        logger.exception("unhandled exception while handling request", exc_info=exc)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    app.add_middleware(CsrfMiddleware)
    if settings.trusted_proxy:
        # Only used to sanity-check Host headers; X-Forwarded-* trust for
        # scheme/cookies is handled by running uvicorn with --proxy-headers.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

    app.include_router(auth.router)
    app.include_router(hosts.router)
    app.include_router(log_sources.router)
    app.include_router(log_sources.global_router)
    app.include_router(dashboards.router)
    app.include_router(ws_logs.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    if STATIC_DIR.is_dir():
        assets_dir = STATIC_DIR / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        index_file = STATIC_DIR / "index.html"

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            # Serve the built SPA for any non-API/WS route (client-side routing,
            # including /view/log/:id and /view/dashboard/:id for hard refreshes).
            candidate = STATIC_DIR / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            if index_file.is_file():
                return FileResponse(index_file)
            return JSONResponse({"detail": "frontend not built"}, status_code=404)
    else:
        logger.warning("Frontend build directory %s not found — API-only mode.", STATIC_DIR)

    return app


app = create_app()
