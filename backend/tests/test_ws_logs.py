"""WebSocket live-tail protocol tests.

Uses Starlette's synchronous TestClient (httpx's AsyncClient has no
WebSocket support) — so this test manages its own env/cache setup instead of
the async `client`/`auth_client` fixtures used elsewhere.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _fresh_app(tmp_path: Path):
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    os.environ["MASTER_KEY"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    os.environ["JWT_SECRET"] = "test-secret-not-for-production-32bytes+"
    os.environ["ADMIN_EMAIL"] = "admin@example.com"
    os.environ["ADMIN_PASSWORD"] = "test-admin-password"
    os.environ["ENV"] = "development"
    os.environ["LOG_BUFFER_MAX_LINES"] = "1000"

    from app import config as config_module
    from app import database as database_module
    from app.security import crypto as crypto_module
    from app.security import jwt as jwt_module
    from app.ssh import pool as ssh_pool_module
    from app.tailing import manager as tailing_manager_module

    config_module.get_settings.cache_clear()
    database_module.reset_engine_cache()
    crypto_module.reset_key_cache()
    jwt_module.reset_secret_cache()
    ssh_pool_module.reset_ssh_pool_for_tests()
    tailing_manager_module.reset_tail_manager_for_tests()

    from app.core.rate_limit import limiter as rate_limiter

    rate_limiter.reset()

    from app.main import create_app

    return create_app()


def test_ws_subscribe_backfill_and_live_line(tmp_path: Path):
    app = _fresh_app(tmp_path)
    log_file = tmp_path / "app.log"
    log_file.write_text("old line 1\nold line 2\n")

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
        assert login.status_code == 200
        csrf = client.cookies["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        host_resp = client.post("/api/hosts", json={"name": "local", "connection_type": "local"}, headers=headers)
        assert host_resp.status_code == 201, host_resp.text
        host_id = host_resp.json()["id"]

        ls_resp = client.post(
            f"/api/hosts/{host_id}/log-sources",
            json={"label": "x", "mode": "exact_path", "path_or_pattern": str(log_file)},
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
                "resolved_path": str(log_file),
            }
            sub_id = subscribed["subscription_id"]

            backfill = ws.receive_json()
            assert backfill == {"type": "backfill", "subscription_id": sub_id, "lines": ["old line 1", "old line 2"]}

            with open(log_file, "a") as f:
                f.write("new line\n")

            line_msg = ws.receive_json()
            assert line_msg == {"type": "line", "subscription_id": sub_id, "text": "new line"}

            ws.send_json({"type": "unsubscribe", "subscription_id": sub_id})


def test_ws_set_filter_returns_matching_lines(tmp_path: Path):
    app = _fresh_app(tmp_path)
    log_file = tmp_path / "app.log"
    log_file.write_text("info: starting\nerror: boom\ninfo: done\n")

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-password"})
        csrf = client.cookies["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        host_id = client.post("/api/hosts", json={"name": "local", "connection_type": "local"}, headers=headers).json()["id"]
        log_source_id = client.post(
            f"/api/hosts/{host_id}/log-sources",
            json={"label": "x", "mode": "exact_path", "path_or_pattern": str(log_file)},
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


@pytest.mark.skipif(shutil.which("journalctl") is None, reason="journalctl not available on this host")
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

        host_id = client.post("/api/hosts", json={"name": "local", "connection_type": "local"}, headers=headers).json()["id"]
        log_source_id = client.post(
            f"/api/hosts/{host_id}/log-sources",
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
