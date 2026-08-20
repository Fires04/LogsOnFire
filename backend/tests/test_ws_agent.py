"""Wire-level /ws/agent protocol tests: real WebSocket handshake + auth +
hello, using Starlette's synchronous TestClient (same reasoning as
test_ws_logs.py — httpx's AsyncClient has no WebSocket support). Complements
the higher-level, in-process fake_agent.py-based tests (test_agents_api.py,
test_browse.py, test_log_sources_resolve.py) which exercise the
resolve/browse/start_tail *logic* without needing a real socket.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from starlette.testclient import TestClient


def _fresh_app(tmp_path: Path):
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    os.environ["AGENT_TOKEN_PEPPER"] = "test-pepper-not-for-production-32bytes+"
    os.environ["JWT_SECRET"] = "test-secret-not-for-production-32bytes+"
    os.environ["ADMIN_EMAIL"] = "admin@example.com"
    os.environ["ADMIN_PASSWORD"] = "test-admin-password"
    os.environ["ENV"] = "development"

    from app import config as config_module
    from app import database as database_module
    from app.agents import registry as agent_registry_module
    from app.security import jwt as jwt_module
    from app.tailing import manager as tailing_manager_module

    config_module.get_settings.cache_clear()
    database_module.reset_engine_cache()
    jwt_module.reset_secret_cache()
    agent_registry_module.reset_agent_registry_for_tests()
    tailing_manager_module.reset_tail_manager_for_tests()

    from app.core.rate_limit import limiter as rate_limiter

    rate_limiter.reset()

    from app.main import create_app

    return create_app()


def _enroll_agent(client: TestClient, headers: dict, name: str) -> tuple[str, str]:
    resp = client.post("/api/agents", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["agent"]["id"], body["token"]


def test_ws_agent_rejects_missing_or_invalid_token(tmp_path: Path):
    app = _fresh_app(tmp_path)
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/ws/agent"):
                raise AssertionError("expected rejection with no Authorization header")
        except Exception:
            pass

        try:
            with client.websocket_connect("/ws/agent", headers={"authorization": "Bearer not-a-real-token"}):
                raise AssertionError("expected rejection with an invalid token")
        except Exception:
            pass


def test_ws_agent_connect_and_hello_update_status(tmp_path: Path):
    app = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
        headers = {"X-CSRF-Token": client.cookies["csrf_token"]}
        agent_id, token = _enroll_agent(client, headers, "wire-test-agent")

        status_before = client.get(f"/api/agents/{agent_id}").json()
        assert status_before["online"] is False

        with client.websocket_connect("/ws/agent", headers={"authorization": f"Bearer {token}"}) as agent_ws:
            status_during = client.get(f"/api/agents/{agent_id}").json()
            assert status_during["online"] is True

            agent_ws.send_json({"type": "hello", "agent_version": "0.1.0-test"})
            # Give the server a moment to process the hello message and commit.
            for _ in range(20):
                status = client.get(f"/api/agents/{agent_id}").json()
                if status["agent_version"] == "0.1.0-test":
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("agent_version was never updated from hello")

            # Close explicitly *while still inside* the `with` block (i.e.
            # while TestClient's background portal/event loop is still
            # fully alive) and poll here too — exiting the `with` block
            # tears down the portal's task group immediately and can cut
            # off the server's still-running disconnect handler
            # (finally: await mark_disconnected(...)) mid-flight, which
            # would make any assertion made *after* the `with` block
            # unreliable no matter how long it polls.
            agent_ws.close()
            for _ in range(40):
                status_after = client.get(f"/api/agents/{agent_id}").json()
                if status_after["online"] is False:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("agent was never marked offline after disconnect")
