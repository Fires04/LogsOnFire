"""WebSocket live-tail protocol tests (browser-facing /ws/logs).

Uses Starlette's synchronous TestClient (httpx's AsyncClient has no
WebSocket support) — so this test manages its own env/cache setup instead of
the async `client`/`auth_client` fixtures used elsewhere. The log source's
"agent" is a fake one (tests/fake_agent.py) attached directly to the
AgentConnectionRegistry — this exercises the real subscribe/backfill/filter
path through tailing/manager.py and tailing/session.py without needing an
actual second WebSocket connection playing the agent role (that wire-level
coverage lives in test_ws_agent.py).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.fake_agent import attach_fake_agent


def _fresh_app(tmp_path: Path):
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    os.environ["AGENT_TOKEN_PEPPER"] = "test-pepper-not-for-production-32bytes+"
    os.environ["JWT_SECRET"] = "test-secret-not-for-production-32bytes+"
    os.environ["ADMIN_EMAIL"] = "admin@example.com"
    os.environ["ADMIN_PASSWORD"] = "test-admin-password"
    os.environ["ENV"] = "development"
    os.environ["LOG_BUFFER_MAX_LINES"] = "1000"

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


def _fake_agent_start_tail_handler(backfill: list[str]):
    def handler(msg: dict) -> dict | None:
        if msg["type"] == "start_tail":
            return {"lines": list(backfill)}
        return None

    return handler


def test_ws_subscribe_backfill_and_live_line(tmp_path: Path):
    app = _fresh_app(tmp_path)

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
        assert login.status_code == 200
        csrf = client.cookies["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        agent_resp = client.post("/api/agents", json={"name": "agent-1"}, headers=headers)
        assert agent_resp.status_code == 201, agent_resp.text
        agent_id = agent_resp.json()["agent"]["id"]

        def handler(msg: dict) -> dict | None:
            if msg["type"] != "start_tail":
                return None
            # Schedule the "new line" push via the *app's own event loop*
            # (call_later, from inside this handler, which already runs on
            # that loop/thread — TestClient runs the app in a background
            # portal thread) rather than mutating the session's asyncio
            # objects from the test's own thread, which would be an unsafe
            # cross-thread asyncio.Queue/Future access.
            from app.tailing.manager import get_tail_manager

            def _push_line() -> None:
                session = get_tail_manager().get_session(agent_id, msg["resolved_path"])
                if session is not None:
                    session.receive_line("new line")

            asyncio.get_running_loop().call_later(0.05, _push_line)
            return {"lines": ["old line 1", "old line 2"]}

        attach_fake_agent(agent_id, handler)

        ls_resp = client.post(
            f"/api/agents/{agent_id}/log-sources",
            json={"label": "x", "mode": "exact_path", "path_or_pattern": "/var/log/app.log"},
            headers=headers,
        )
        assert ls_resp.status_code == 201, ls_resp.text
        log_source_id = ls_resp.json()["id"]

        with client.websocket_connect("/ws/logs") as ws:
            ws.send_json({"type": "subscribe", "req_id": "r1", "log_source_id": log_source_id})

            subscribed = ws.receive_json()
            assert subscribed == {
                "type": "subscribed",
                "req_id": "r1",
                "subscription_id": subscribed["subscription_id"],
                "resolved_path": "/var/log/app.log",
            }
            sub_id = subscribed["subscription_id"]

            backfill = ws.receive_json()
            assert backfill == {"type": "backfill", "subscription_id": sub_id, "lines": ["old line 1", "old line 2"]}

            line_msg = ws.receive_json()
            assert line_msg == {"type": "line", "subscription_id": sub_id, "text": "new line"}

            ws.send_json({"type": "unsubscribe", "subscription_id": sub_id})


def test_ws_set_filter_returns_matching_lines(tmp_path: Path):
    app = _fresh_app(tmp_path)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
        csrf = client.cookies["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        agent_id = client.post("/api/agents", json={"name": "agent-1"}, headers=headers).json()["agent"]["id"]
        attach_fake_agent(
            agent_id, _fake_agent_start_tail_handler(["info: starting", "error: boom", "info: done"])
        )
        log_source_id = client.post(
            f"/api/agents/{agent_id}/log-sources",
            json={"label": "x", "mode": "exact_path", "path_or_pattern": "/var/log/app.log"},
            headers=headers,
        ).json()["id"]

        with client.websocket_connect("/ws/logs") as ws:
            ws.send_json({"type": "subscribe", "req_id": "r1", "log_source_id": log_source_id})
            subscribed = ws.receive_json()
            sub_id = subscribed["subscription_id"]
            ws.receive_json()  # backfill

            ws.send_json({"type": "set_filter", "subscription_id": sub_id, "expression": "error"})
            snapshot = ws.receive_json()
            assert snapshot["type"] == "filtered_snapshot"
            matches = [line for line in snapshot["lines"] if line["is_match"]]
            assert len(matches) == 1
            assert "boom" in matches[0]["text"]

            ws.send_json({"type": "clear_filter", "subscription_id": sub_id})
            restored = ws.receive_json()
            assert restored["type"] == "backfill"
            assert restored["lines"] == ["info: starting", "error: boom", "info: done"]


def test_ws_subscribe_unknown_log_source_returns_error(tmp_path: Path):
    app = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
        with client.websocket_connect("/ws/logs") as ws:
            ws.send_json({"type": "subscribe", "req_id": "r1", "log_source_id": "does-not-exist"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert msg["req_id"] == "r1"


def test_ws_subscribe_offline_agent_returns_error(tmp_path: Path):
    app = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
        csrf = client.cookies["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        agent_id = client.post("/api/agents", json={"name": "offline"}, headers=headers).json()["agent"]["id"]
        # Deliberately not attaching a fake agent — it stays offline.
        log_source_id = client.post(
            f"/api/agents/{agent_id}/log-sources",
            json={"label": "x", "mode": "exact_path", "path_or_pattern": "/var/log/app.log"},
            headers=headers,
        ).json()["id"]

        with client.websocket_connect("/ws/logs") as ws:
            ws.send_json({"type": "subscribe", "req_id": "r1", "log_source_id": log_source_id})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert msg["req_id"] == "r1"


def test_ws_subscribe_journal_mode_without_client_resolved_path(tmp_path: Path):
    """Regression test: journal-mode log sources are deterministic like
    exact_path (no client-side pattern-match step) — subscribing without the
    client supplying `resolved_path` must work, not bounce with
    'resolved_path is required for glob/regex log sources'.
    """
    app = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
        csrf = client.cookies["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        agent_id = client.post("/api/agents", json={"name": "agent-journal"}, headers=headers).json()["agent"]["id"]
        attach_fake_agent(agent_id, _fake_agent_start_tail_handler([]))
        log_source_id = client.post(
            f"/api/agents/{agent_id}/log-sources",
            json={"label": "journal", "mode": "journal", "path_or_pattern": "*"},
            headers=headers,
        ).json()["id"]

        with client.websocket_connect("/ws/logs") as ws:
            ws.send_json({"type": "subscribe", "req_id": "r1", "log_source_id": log_source_id})
            subscribed = ws.receive_json()
            assert subscribed["type"] == "subscribed", subscribed
            assert subscribed["resolved_path"] == "journal://"

            backfill = ws.receive_json()
            assert backfill["type"] == "backfill"

            ws.send_json({"type": "unsubscribe", "subscription_id": subscribed["subscription_id"]})


def test_ws_requires_authentication(tmp_path: Path):
    app = _fresh_app(tmp_path)
    with TestClient(app) as client:
        # Deliberately not logging in — no auth cookie present.
        try:
            with client.websocket_connect("/ws/logs"):
                raise AssertionError("expected the connection to be rejected")
        except Exception:
            pass  # starlette raises WebSocketDisconnect (or similar) on a 4401 close during handshake
