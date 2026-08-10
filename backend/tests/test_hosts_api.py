from __future__ import annotations

from httpx import AsyncClient


async def test_create_and_list_local_host(auth_client: AsyncClient):
    resp = await auth_client.post("/api/hosts", json={"name": "local-box", "connection_type": "local"})
    assert resp.status_code == 201, resp.text
    host = resp.json()
    assert host["connection_type"] == "local"
    assert host["has_password"] is False

    listing = await auth_client.get("/api/hosts")
    assert listing.status_code == 200
    assert any(h["id"] == host["id"] for h in listing.json())


async def test_create_ssh_host_requires_credentials(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/hosts",
        json={
            "name": "sshbox",
            "connection_type": "ssh",
            "hostname": "example.invalid",
            "ssh_username": "root",
            "auth_type": "password",
            # no password provided -> should fail validation
        },
    )
    assert resp.status_code == 422


async def test_create_ssh_host_stores_encrypted_credential(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/hosts",
        json={
            "name": "sshbox",
            "connection_type": "ssh",
            "hostname": "example.invalid",
            "ssh_username": "root",
            "auth_type": "password",
            "password": "supersecret",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["has_password"] is True
    # The plaintext password must never come back through the API.
    assert "password" not in body


async def test_local_host_test_connection_is_noop_success(auth_client: AsyncClient):
    create = await auth_client.post("/api/hosts", json={"name": "local-box", "connection_type": "local"})
    host_id = create.json()["id"]
    resp = await auth_client.post(f"/api/hosts/{host_id}/test-connection")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_unreachable_ssh_host_test_connection_fails_cleanly(auth_client: AsyncClient):
    create = await auth_client.post(
        "/api/hosts",
        json={
            "name": "unreachable",
            "connection_type": "ssh",
            "hostname": "127.0.0.1",
            "port": 1,  # nothing listens here
            "ssh_username": "root",
            "auth_type": "password",
            "password": "whatever",
        },
    )
    host_id = create.json()["id"]
    resp = await auth_client.post(f"/api/hosts/{host_id}/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "connect" in body["message"].lower() or "refused" in body["message"].lower()


async def test_delete_host(auth_client: AsyncClient):
    create = await auth_client.post("/api/hosts", json={"name": "to-delete", "connection_type": "local"})
    host_id = create.json()["id"]
    resp = await auth_client.delete(f"/api/hosts/{host_id}")
    assert resp.status_code == 204
    listing = await auth_client.get("/api/hosts")
    assert all(h["id"] != host_id for h in listing.json())
