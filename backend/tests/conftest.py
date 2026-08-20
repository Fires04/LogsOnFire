from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """A fresh app + isolated temp SQLite DB per test."""
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.db")

    os.environ["DB_PATH"] = db_path
    os.environ["AGENT_TOKEN_PEPPER"] = "test-pepper-not-for-production-32bytes+"
    os.environ["JWT_SECRET"] = "test-secret-not-for-production-32bytes+"
    os.environ["ADMIN_EMAIL"] = "admin@example.com"
    os.environ["ADMIN_PASSWORD"] = "test-admin-password"
    os.environ["ENV"] = "development"

    # Reset every module-level cache that could leak state between tests.
    from app import config as config_module
    from app import database as database_module
    from app.agents import registry as agent_registry_module
    from app.security import jwt as jwt_module
    from app.tailing import manager as tailing_manager_module

    config_module.get_settings.cache_clear()
    database_module.reset_engine_cache()
    jwt_module.reset_secret_cache()
    agent_registry_module.reset_agent_registry_for_tests()
    tailing_manager_module.reset_tail_manager_for_tests()

    # The rate limiter's in-memory counters are process-wide (module-level
    # singleton), not per-app — without resetting, tests would accumulate
    # login attempts across the whole suite and start hitting 429s.
    from app.core.rate_limit import limiter as rate_limiter

    rate_limiter.reset()

    from app.bootstrap import bootstrap
    from app.main import create_app

    await bootstrap()
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    resp = await client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"}
    )
    assert resp.status_code == 200, resp.text
    client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
    return client
