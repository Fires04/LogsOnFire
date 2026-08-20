from __future__ import annotations

from httpx import AsyncClient


async def test_create_and_list_saved_filter(auth_client: AsyncClient):
    resp = await auth_client.post("/api/saved-filters", json={"label": "errors", "expression": "-i error -C 3"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["label"] == "errors"
    assert body["expression"] == "-i error -C 3"

    listing = await auth_client.get("/api/saved-filters")
    assert listing.status_code == 200
    assert any(f["id"] == body["id"] for f in listing.json())


async def test_delete_saved_filter(auth_client: AsyncClient):
    create = await auth_client.post("/api/saved-filters", json={"label": "to-delete", "expression": "-v debug"})
    filter_id = create.json()["id"]

    resp = await auth_client.delete(f"/api/saved-filters/{filter_id}")
    assert resp.status_code == 204

    listing = await auth_client.get("/api/saved-filters")
    assert all(f["id"] != filter_id for f in listing.json())


async def test_delete_missing_saved_filter_404s(auth_client: AsyncClient):
    resp = await auth_client.delete("/api/saved-filters/does-not-exist")
    assert resp.status_code == 404


async def test_saved_filters_require_login(client: AsyncClient):
    resp = await client.get("/api/saved-filters")
    assert resp.status_code == 401
