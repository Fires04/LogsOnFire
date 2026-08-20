"""REST-layer /api/agents/{id}/browse tests. Provider-level directory
listing behavior (sorting, permissions/readability reporting,
default_browse_path) now lives in agentcore/tests/test_local_provider.py,
next to the code that implements it (LocalFileProvider runs inside the
agent process, not the server, since pull-over-SSH/local was removed).
"""
from __future__ import annotations

from httpx import AsyncClient

from tests.fake_agent import attach_fake_agent


async def test_browse_endpoint_reports_missing_directory_as_clean_error(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "agent-1"})
    agent_id = create.json()["agent"]["id"]

    attach_fake_agent(
        agent_id,
        lambda msg: {"path": msg.get("path") or "/", "parent": None, "entries": [], "truncated": False, "error": "no such directory"},
    )

    resp = await auth_client.get(f"/api/agents/{agent_id}/browse", params={"path": "/nope"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is not None
    assert body["entries"] == []


async def test_browse_endpoint_reports_parent_even_when_listing_fails(auth_client: AsyncClient):
    """Regression: a directory that fails to list (e.g. permission denied)
    used to come back with parent=None, disabling the "Up" button exactly
    when the user needs it most to back out of it. The agent's browse
    handler is responsible for computing `parent` unconditionally — this
    test just confirms the server passes that through rather than
    clobbering it on the error path.
    """
    create = await auth_client.post("/api/agents", json={"name": "agent-2"})
    agent_id = create.json()["agent"]["id"]

    attach_fake_agent(
        agent_id,
        lambda msg: {"path": "/blocked", "parent": "/", "entries": [], "truncated": False, "error": "permission denied"},
    )

    resp = await auth_client.get(f"/api/agents/{agent_id}/browse", params={"path": "/blocked"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is not None
    assert body["parent"] == "/"


async def test_browse_endpoint_defaults_to_agents_own_root_when_no_path_given(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "agent-3"})
    agent_id = create.json()["agent"]["id"]

    def handler(msg: dict) -> dict:
        assert msg.get("path") is None  # server passes through "no path given" as-is
        return {"path": "/home/agent-user", "parent": "/home", "entries": [], "truncated": False}

    attach_fake_agent(agent_id, handler)

    resp = await auth_client.get(f"/api/agents/{agent_id}/browse")
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "/home/agent-user"
    assert body["parent"] == "/home"
