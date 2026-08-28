"""Tests for the optional Authentik/OIDC login bolted onto the password
path (api/routes/auth.py's oidc_login/oidc_callback). fireauth.oidc's own
OIDCClient isn't meaningfully testable without a live IdP (per its own
README) — these tests monkeypatch app.api.routes.auth._get_oidc_client
instead, at the same boundary FireAuth's own README recommends verifying
by hand against a real Authentik.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from starlette.responses import RedirectResponse

from app.api.routes import auth as auth_routes


class _FakeOidcClient:
    def __init__(self, userinfo: dict | None) -> None:
        self._userinfo = userinfo

    async def login_redirect(self, request):
        return RedirectResponse(url="https://authentik.example/authorize", status_code=302)

    async def handle_callback(self, request):
        return self._userinfo or {}


def _patch_oidc_client(monkeypatch: pytest.MonkeyPatch, userinfo: dict | None) -> None:
    fake = _FakeOidcClient(userinfo)
    monkeypatch.setattr(auth_routes, "_get_oidc_client", lambda: fake)


async def test_oidc_routes_404_when_not_configured(client: AsyncClient):
    # No OIDC_CLIENT_ID set in the test env (see conftest.py) —
    # oidc_enabled is False, so both routes must not exist.
    login_resp = await client.get("/api/auth/oidc/login", follow_redirects=False)
    assert login_resp.status_code == 404
    callback_resp = await client.get("/api/auth/oidc/callback", follow_redirects=False)
    assert callback_resp.status_code == 404


async def test_oidc_login_redirects_to_provider(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_oidc_client(monkeypatch, userinfo=None)
    resp = await client.get("/api/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://authentik.example/authorize"


async def test_oidc_callback_matching_email_issues_cookies(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_oidc_client(monkeypatch, userinfo={"email": "admin@example.com", "preferred_username": "admin"})
    resp = await client.get("/api/auth/oidc/callback", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies

    client.cookies.update(resp.cookies)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"


async def test_oidc_callback_unmapped_email_does_not_log_in(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_oidc_client(monkeypatch, userinfo={"email": "nobody@example.com"})
    resp = await client.get("/api/auth/oidc/callback", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?error=oidc_unmapped"
    assert "access_token" not in resp.cookies

    client.cookies.update(resp.cookies)
    me = await client.get("/api/auth/me")
    assert me.status_code == 401


async def test_health_reports_oidc_enabled(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["oidc_enabled"] is False


async def test_oidc_client_wires_up_when_configured(monkeypatch: pytest.MonkeyPatch):
    """Config-driven wiring, independent of the fake-client tests above:
    with OIDC_CLIENT_ID set, _get_oidc_client() must actually build a
    real fireauth OIDCClient (not None) — constructing it does no network
    I/O (authlib only hits the issuer's discovery document lazily, on the
    first real authorize/callback call), so this is safe to assert without
    a live IdP."""
    from app import config as config_module

    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("OIDC_ISSUER", "https://authentik.example/application/o/fireslog/")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://fireslog.example/api/auth/oidc/callback")
    config_module.get_settings.cache_clear()
    auth_routes.reset_oidc_client_for_tests()

    assert config_module.get_settings().oidc_enabled is True
    from fireauth.oidc import OIDCClient

    oidc = auth_routes._get_oidc_client()
    assert isinstance(oidc, OIDCClient)

    config_module.get_settings.cache_clear()
    auth_routes.reset_oidc_client_for_tests()


async def test_oidc_callback_inactive_user_does_not_log_in(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    # Deactivate the seeded admin, then try to sign in via OIDC as them —
    # must be treated the same as "no match", not silently let through.
    from sqlalchemy import select

    from app.database import get_session_factory
    from app.models.user import User

    async with get_session_factory()() as db:
        result = await db.execute(select(User).where(User.email == "admin@example.com"))
        user = result.scalar_one()
        user.is_active = False
        await db.commit()

    _patch_oidc_client(monkeypatch, userinfo={"email": "admin@example.com"})
    resp = await client.get("/api/auth/oidc/callback", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?error=oidc_unmapped"
