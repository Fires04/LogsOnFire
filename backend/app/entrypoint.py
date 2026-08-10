"""Production entrypoint (`python -m app.entrypoint`).

IMPORTANT: this explicitly forces uvicorn's plain `asyncio` event loop
instead of `uvloop` (uvicorn's default when the `[standard]` extra is
installed, which it is here). Under uvloop, this app hangs completely
during startup — SQLAlchemy's async engine uses `greenlet` to bridge sync
DBAPI calls (aiosqlite's worker thread) back into async code, and that
bridging does not resolve under uvloop in this setup. This was found by
direct testing, not a hypothetical: `uvicorn ... ` with default settings
hangs forever after "Running upgrade -> 0001"; `--loop asyncio` fixes it
immediately. Do not drop `loop="asyncio"` without re-verifying this.
"""
from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        loop="asyncio",
        proxy_headers=settings.trusted_proxy,
        forwarded_allow_ips="*" if settings.trusted_proxy else None,
    )


if __name__ == "__main__":
    main()
