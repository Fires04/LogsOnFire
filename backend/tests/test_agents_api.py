from __future__ import annotations

from httpx import AsyncClient

from app.agents.registry import get_agent_registry
from tests.fake_agent import attach_fake_agent


async def test_create_agent_returns_token_once_and_never_again(auth_client: AsyncClient):
    resp = await auth_client.post("/api/agents", json={"name": "web-01"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent"]["name"] == "web-01"
    assert body["agent"]["online"] is False
    assert len(body["token"]) > 20
    assert body["agent"]["token_prefix"] == body["token"][:12]

    listing = await auth_client.get("/api/agents")
    assert listing.status_code == 200
    assert all("token" not in a for a in listing.json())
    agent = next(a for a in listing.json() if a["id"] == body["agent"]["id"])
    assert "token" not in agent


async def test_agent_online_reflects_live_connection(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "web-02"})
    agent_id = create.json()["agent"]["id"]

    from app.agents.service import mark_connected, mark_disconnected
    from app.database import get_session_factory
    from app.models.agent import Agent
    from sqlalchemy import select

    async with get_session_factory()() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one()
        attach_fake_agent(agent_id, lambda _msg: None)
        await mark_connected(db, agent, agent_version="0.1.0")

    resp = await auth_client.get(f"/api/agents/{agent_id}")
    assert resp.json()["online"] is True
    assert resp.json()["agent_version"] == "0.1.0"

    async with get_session_factory()() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one()
        await mark_disconnected(db, agent)

    resp = await auth_client.get(f"/api/agents/{agent_id}")
    assert resp.json()["online"] is False


async def test_reissue_token_changes_prefix_and_disconnects_live_agent(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "web-03"})
    agent_id = create.json()["agent"]["id"]
    old_token = create.json()["token"]

    attach_fake_agent(agent_id, lambda _msg: None)
    assert get_agent_registry().is_connected(agent_id)

    resp = await auth_client.post(f"/api/agents/{agent_id}/reissue-token")
    assert resp.status_code == 200, resp.text
    new_token = resp.json()["token"]
    assert new_token != old_token
    assert resp.json()["agent"]["token_prefix"] == new_token[:12]


async def test_rename_agent(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "old-name"})
    agent_id = create.json()["agent"]["id"]

    resp = await auth_client.patch(f"/api/agents/{agent_id}", json={"name": "new-name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "new-name"


async def test_delete_agent(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "to-delete"})
    agent_id = create.json()["agent"]["id"]

    resp = await auth_client.delete(f"/api/agents/{agent_id}")
    assert resp.status_code == 204
    listing = await auth_client.get("/api/agents")
    assert all(a["id"] != agent_id for a in listing.json())


async def test_browse_offline_agent_returns_clean_error(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "never-connected"})
    agent_id = create.json()["agent"]["id"]

    resp = await auth_client.get(f"/api/agents/{agent_id}/browse")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is not None
    assert "offline" in body["error"].lower()


async def test_agent_notes_create_and_update(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "with-notes", "notes": "rack 3, proxmox node"})
    assert create.status_code == 201, create.text
    agent_id = create.json()["agent"]["id"]
    assert create.json()["agent"]["notes"] == "rack 3, proxmox node"

    resp = await auth_client.patch(f"/api/agents/{agent_id}", json={"notes": "moved to rack 4"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "moved to rack 4"

    resp = await auth_client.get(f"/api/agents/{agent_id}")
    assert resp.json()["notes"] == "moved to rack 4"


async def test_agent_created_without_notes_defaults_to_none(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "no-notes"})
    assert create.status_code == 201, create.text
    assert create.json()["agent"]["notes"] is None


async def test_trigger_update_offline_agent_returns_clean_error(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "update-offline"})
    agent_id = create.json()["agent"]["id"]

    resp = await auth_client.post(f"/api/agents/{agent_id}/trigger-update")
    assert resp.status_code == 200
    body = resp.json()
    assert body["started"] is False
    assert "offline" in body["error"].lower()


async def test_trigger_update_connected_agent_forwards_ack(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "update-connected"})
    agent_id = create.json()["agent"]["id"]

    def handler(msg: dict) -> dict | None:
        if msg["type"] == "self_update":
            return {"started": True}
        return None

    attach_fake_agent(agent_id, handler)

    resp = await auth_client.post(f"/api/agents/{agent_id}/trigger-update")
    assert resp.status_code == 200
    assert resp.json() == {"started": True, "error": None}


async def test_journal_units_offline_agent_returns_clean_error(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "units-offline"})
    agent_id = create.json()["agent"]["id"]

    resp = await auth_client.get(f"/api/agents/{agent_id}/journal-units")
    assert resp.status_code == 200
    body = resp.json()
    assert body["units"] == []
    assert "offline" in body["error"].lower()


async def test_journal_units_connected_agent_returns_list(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "units-connected"})
    agent_id = create.json()["agent"]["id"]

    def handler(msg: dict) -> dict | None:
        if msg["type"] == "list_units":
            return {"units": ["nginx.service", "sshd.service"]}
        return None

    attach_fake_agent(agent_id, handler)

    resp = await auth_client.get(f"/api/agents/{agent_id}/journal-units")
    assert resp.status_code == 200
    assert resp.json()["units"] == ["nginx.service", "sshd.service"]


async def test_docker_containers_connected_agent_returns_list(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "containers-connected"})
    agent_id = create.json()["agent"]["id"]

    def handler(msg: dict) -> dict | None:
        if msg["type"] == "list_containers":
            return {"containers": ["immich_server"]}
        return None

    attach_fake_agent(agent_id, handler)

    resp = await auth_client.get(f"/api/agents/{agent_id}/docker-containers")
    assert resp.status_code == 200
    assert resp.json()["containers"] == ["immich_server"]


async def test_browse_connected_agent_returns_entries(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "connected-browse"})
    agent_id = create.json()["agent"]["id"]

    def handler(msg: dict) -> dict | None:
        if msg["type"] == "browse":
            return {
                "path": "/var/log",
                "parent": "/var",
                "entries": [{"name": "syslog", "path": "/var/log/syslog", "is_dir": False}],
                "truncated": False,
            }
        return None

    attach_fake_agent(agent_id, handler)

    resp = await auth_client.get(f"/api/agents/{agent_id}/browse")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["path"] == "/var/log"
    assert body["entries"][0]["name"] == "syslog"
