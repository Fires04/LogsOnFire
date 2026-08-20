"""Tests for the one-time install-link flow: POST .../install-link creates
a short single-use code; GET /agent/install/{code} returns a script with
--server/--token baked in (never as CLI args a real deployment would leave
in shell history) and is only ever usable once.
"""
from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient


async def _create_agent(client: AsyncClient) -> tuple[str, str]:
    resp = await client.post("/api/agents", json={"name": "install-link-agent"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["agent"]["id"], body["token"]


async def test_install_link_rejects_bad_scheme(auth_client: AsyncClient):
    agent_id, token = await _create_agent(auth_client)
    resp = await auth_client.post(
        f"/api/agents/{agent_id}/install-link", json={"token": token, "server_url": "http://not-a-ws-url:8000"}
    )
    assert resp.status_code == 422


async def test_install_link_download_embeds_server_and_token(auth_client: AsyncClient, tmp_path: Path, monkeypatch):
    template = tmp_path / "install.sh"
    template.write_text("#!/usr/bin/env bash\necho hello\n")

    from app.api.routes import agent_install as agent_install_module

    monkeypatch.setattr(agent_install_module, "INSTALL_SH_TEMPLATE", template)

    agent_id, token = await _create_agent(auth_client)
    link_resp = await auth_client.post(
        f"/api/agents/{agent_id}/install-link", json={"token": token, "server_url": "ws://example.invalid:8000"}
    )
    assert link_resp.status_code == 200, link_resp.text
    code = link_resp.json()["code"]
    assert link_resp.json()["expires_in_seconds"] > 0

    download_resp = await auth_client.get(f"/agent/install/{code}")
    assert download_resp.status_code == 200
    script = download_resp.text
    assert script.startswith("#!/usr/bin/env bash\n")
    assert f"export LOGSONFIRE_INSTALL_SERVER={ws_quoted('ws://example.invalid:8000')}" in script
    assert f"export LOGSONFIRE_INSTALL_TOKEN={ws_quoted(token)}" in script
    assert "echo hello" in script
    # The real token must never leak into the code itself.
    assert token not in code


async def test_install_link_is_single_use(auth_client: AsyncClient, tmp_path: Path, monkeypatch):
    template = tmp_path / "install.sh"
    template.write_text("#!/usr/bin/env bash\necho hello\n")

    from app.api.routes import agent_install as agent_install_module

    monkeypatch.setattr(agent_install_module, "INSTALL_SH_TEMPLATE", template)

    agent_id, token = await _create_agent(auth_client)
    link_resp = await auth_client.post(
        f"/api/agents/{agent_id}/install-link", json={"token": token, "server_url": "ws://example.invalid:8000"}
    )
    code = link_resp.json()["code"]

    first = await auth_client.get(f"/agent/install/{code}")
    assert first.status_code == 200

    second = await auth_client.get(f"/agent/install/{code}")
    assert second.status_code == 410


async def test_unknown_install_code_returns_410(auth_client: AsyncClient):
    resp = await auth_client.get("/agent/install/this-code-was-never-issued")
    assert resp.status_code == 410


def ws_quoted(value: str) -> str:
    import shlex

    return shlex.quote(value)
