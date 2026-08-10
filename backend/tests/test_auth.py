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
    resp = await client.post("/api/hosts", json={"name": "x", "connection_type": "local"})
    assert resp.status_code == 403


async def test_logout_clears_cookies(auth_client: AsyncClient):
    resp = await auth_client.post("/api/auth/logout")
    assert resp.status_code == 200
    me = await auth_client.get("/api/auth/me")
    assert me.status_code == 401
