from __future__ import annotations

from httpx import AsyncClient


async def test_login_success_sets_cookies(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "admin@example.com"
    assert body["is_admin"] is True
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies
    assert "csrf_token" in resp.cookies


async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "nope"})
    assert resp.status_code == 401


async def test_me_requires_auth(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_after_login(auth_client: AsyncClient):
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@example.com"


async def test_mutating_request_requires_csrf_header(client: AsyncClient):
    await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
    # Deliberately not setting the X-CSRF-Token header.
    resp = await client.post("/api/agents", json={"name": "x"})
    assert resp.status_code == 403


async def test_logout_clears_cookies(auth_client: AsyncClient):
    resp = await auth_client.post("/api/auth/logout")
    assert resp.status_code == 200
    me = await auth_client.get("/api/auth/me")
    assert me.status_code == 401


async def test_remember_me_extends_refresh_token_lifetime(client: AsyncClient):
    from app.config import get_settings

    settings = get_settings()

    without = await client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"}
    )
    refresh_cookie = next(c for c in without.cookies.jar if c.name == "refresh_token")

    client.cookies.clear()
    remembered = await client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "test-admin-password", "remember": True},
    )
    remembered_cookie = next(c for c in remembered.cookies.jar if c.name == "refresh_token")

    # Both requests happen back-to-back, so comparing the two cookies'
    # absolute expiry timestamps directly is reliable enough — remember=True
    # must expire measurably later than remember=False.
    assert remembered_cookie.expires - refresh_cookie.expires > (settings.remember_me_ttl_days - settings.refresh_token_ttl_days - 1) * 86400


async def test_refresh_rolls_remember_me_forward(client: AsyncClient):
    login = await client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "test-admin-password", "remember": True},
    )
    original_refresh_expiry = next(c for c in login.cookies.jar if c.name == "refresh_token").expires
    client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]

    refreshed = await client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    new_refresh_expiry = next(c for c in refreshed.cookies.jar if c.name == "refresh_token").expires

    # If "remember" hadn't rolled forward, the new refresh token would fall
    # back to the short default TTL and expire *sooner* than the original
    # long-lived one, not later/equal.
    assert new_refresh_expiry >= original_refresh_expiry


async def test_expired_access_token_is_silently_refreshed_not_401ed(client: AsyncClient):
    """Simulates what lib/api.ts's tryRefresh() does client-side: an
    expired-but-refreshable session should recover via /api/auth/refresh
    without the user seeing a 401 that bounces them to the login page."""
    await client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password", "remember": True}
    )
    client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]

    # Force the access token to look expired without waiting 15 real
    # minutes: drop it so /api/auth/me 401s, exactly like real expiry would.
    del client.cookies["access_token"]

    stale = await client.get("/api/auth/me")
    assert stale.status_code == 401

    refresh = await client.post("/api/auth/refresh")
    assert refresh.status_code == 200

    recovered = await client.get("/api/auth/me")
    assert recovered.status_code == 200
    assert recovered.json()["email"] == "admin@example.com"
