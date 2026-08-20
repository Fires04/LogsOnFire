"""REST-layer log-source resolve tests. Provider-level pattern-matching
behavior (glob/regex/exact_path semantics, read_tail) now lives in
agentcore/tests/test_local_provider.py, next to the code that implements it.
"""
from __future__ import annotations

from httpx import AsyncClient

from tests.fake_agent import attach_fake_agent


async def test_resolve_preview_offline_agent_returns_clean_error(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "offline-agent"})
    agent_id = create.json()["agent"]["id"]

    resp = await auth_client.post(
        f"/api/agents/{agent_id}/log-sources/resolve-preview",
        json={"label": "x", "mode": "exact_path", "path_or_pattern": "/var/log/syslog"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is not None
    assert "offline" in body["error"].lower()
    assert body["files"] == []


async def test_resolve_preview_connected_agent_returns_files(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "connected-agent"})
    agent_id = create.json()["agent"]["id"]

    def handler(msg: dict) -> dict | None:
        if msg["type"] == "resolve":
            assert msg["log_source"]["mode"] == "glob"
            return {"files": [{"path": "/var/log/app.log", "size": 123, "mtime": 1.0}], "truncated": False}
        return None

    attach_fake_agent(agent_id, handler)

    resp = await auth_client.post(
        f"/api/agents/{agent_id}/log-sources/resolve-preview",
        json={"label": "x", "mode": "glob", "path_or_pattern": "/var/log/*.log"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["files"] == [{"path": "/var/log/app.log", "size": 123, "mtime": 1.0}]


async def test_resolve_saved_log_source_uses_its_stored_pattern(auth_client: AsyncClient):
    create = await auth_client.post("/api/agents", json={"name": "resolve-saved"})
    agent_id = create.json()["agent"]["id"]

    seen_patterns: list[str] = []

    def handler(msg: dict) -> dict | None:
        if msg["type"] == "resolve":
            seen_patterns.append(msg["log_source"]["path_or_pattern"])
            return {"files": [], "truncated": False, "warning": "no matches yet"}
        return None

    attach_fake_agent(agent_id, handler)

    created = await auth_client.post(
        f"/api/agents/{agent_id}/log-sources",
        json={"label": "app", "mode": "exact_path", "path_or_pattern": "/var/log/app.log"},
    )
    log_source_id = created.json()["id"]

    resp = await auth_client.post(f"/api/agents/{agent_id}/log-sources/{log_source_id}/resolve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["warning"] == "no matches yet"
    assert seen_patterns == ["/var/log/app.log"]
