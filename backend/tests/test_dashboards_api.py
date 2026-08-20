from __future__ import annotations

from httpx import AsyncClient


async def _make_agent_and_log_source(client: AsyncClient) -> str:
    agent = await client.post("/api/agents", json={"name": "agent"})
    agent_id = agent.json()["agent"]["id"]
    ls = await client.post(
        f"/api/agents/{agent_id}/log-sources",
        json={"label": "x", "mode": "exact_path", "path_or_pattern": "/tmp/does-not-need-to-exist.log"},
    )
    return ls.json()["id"]


async def test_create_and_list_dashboard(auth_client: AsyncClient):
    log_source_id = await _make_agent_and_log_source(auth_client)

    resp = await auth_client.post(
        "/api/dashboards",
        json={
            "name": "Prod overview",
            "panels": [
                {"log_source_id": log_source_id, "position_x": 0, "position_y": 0, "width": 6, "height": 4}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Prod overview"
    assert len(body["panels"]) == 1
    assert body["panels"][0]["log_source_id"] == log_source_id

    listing = await auth_client.get("/api/dashboards")
    assert any(d["id"] == body["id"] for d in listing.json())


async def test_get_dashboard(auth_client: AsyncClient):
    log_source_id = await _make_agent_and_log_source(auth_client)
    create = await auth_client.post("/api/dashboards", json={"name": "d1", "panels": []})
    dashboard_id = create.json()["id"]

    resp = await auth_client.get(f"/api/dashboards/{dashboard_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "d1"
    assert resp.json()["panels"] == []
    _ = log_source_id  # unused here, just ensuring agent/log-source creation doesn't interfere


async def test_update_dashboard_replaces_panels(auth_client: AsyncClient):
    log_source_id = await _make_agent_and_log_source(auth_client)
    create = await auth_client.post(
        "/api/dashboards",
        json={"name": "d1", "panels": [{"log_source_id": log_source_id}]},
    )
    dashboard_id = create.json()["id"]
    assert len(create.json()["panels"]) == 1

    resp = await auth_client.patch(
        f"/api/dashboards/{dashboard_id}",
        json={"name": "d1 renamed", "panels": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "d1 renamed"
    assert body["panels"] == []


async def test_delete_dashboard(auth_client: AsyncClient):
    create = await auth_client.post("/api/dashboards", json={"name": "to-delete", "panels": []})
    dashboard_id = create.json()["id"]

    resp = await auth_client.delete(f"/api/dashboards/{dashboard_id}")
    assert resp.status_code == 204

    listing = await auth_client.get("/api/dashboards")
    assert all(d["id"] != dashboard_id for d in listing.json())


async def test_get_missing_dashboard_404(auth_client: AsyncClient):
    resp = await auth_client.get("/api/dashboards/does-not-exist")
    assert resp.status_code == 404
