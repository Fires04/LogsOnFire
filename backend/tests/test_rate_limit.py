from __future__ import annotations

from httpx import AsyncClient


async def test_login_is_rate_limited_after_repeated_attempts(client: AsyncClient):
    # LOGIN_RATE_LIMIT is 10/minute; the 11th attempt within the window
    # should be rejected regardless of whether the credentials are valid.
    for _ in range(10):
        resp = await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"})
        assert resp.status_code == 401

    resp = await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"})
    assert resp.status_code == 429
