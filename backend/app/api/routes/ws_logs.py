"""The live-tail WebSocket endpoint.

One WebSocket connection is meant to be opened per browser tab/page and
multiplexed across every log panel on that page via JSON `subscribe`
messages — see the protocol summary below. The heavy lifting (avoiding
redundant SSH connections / remote `tail` processes for the same file) is
already handled by tailing/manager.py + ssh/pool.py; this module is just the
protocol glue between a WebSocket and one or more TailSessions.

Client -> server messages:
    {"type": "subscribe", "req_id", "log_source_id", "resolved_path"?, "tail_lines"?}
    {"type": "unsubscribe", "subscription_id"}
    {"type": "set_filter", "subscription_id", "expression"}
    {"type": "clear_filter", "subscription_id"}
    {"type": "ping"}

Server -> client messages:
    {"type": "subscribed", "req_id", "subscription_id", "resolved_path"}
    {"type": "backfill", "subscription_id", "lines": [str, ...]}
    {"type": "line", "subscription_id", "text"}
    {"type": "filtered_snapshot", "subscription_id", "lines": [{"line_no","text","is_match","is_separator"}]}
    {"type": "filter_error", "subscription_id", "message"}
    {"type": "error", "subscription_id"? , "req_id"?, "message"}
    {"type": "closed", "subscription_id", "reason"}
    {"type": "reauth_required"}
    {"type": "pong"}
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import time
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import record as audit_record
from app.core.permissions import LOG_VIEW
from app.database import get_db
from app.models.log_source import LogSource
from app.models.user import User
from app.core.docker_paths import make_docker_path
from app.core.journal_paths import make_journal_path
from app.security.deps import ACCESS_COOKIE, has_permission
from app.security.jwt import decode_token
from app.tailing.broker import TailClosed, TailError, TailLine
from app.tailing.grep import run_grep
from app.tailing.manager import get_tail_manager

router = APIRouter(tags=["ws"])
logger = logging.getLogger("logsonfire.ws")

FILTER_DEBOUNCE_SECONDS = 0.3


class Subscription:
    __slots__ = ("session", "queue", "filter_expression", "filter_dirty", "forward_task")

    def __init__(self, session, queue) -> None:
        self.session = session
        self.queue = queue
        self.filter_expression: str | None = None
        self.filter_dirty = False
        self.forward_task: asyncio.Task | None = None


async def _authenticate(websocket: WebSocket, db: AsyncSession) -> tuple[User | None, dict[str, Any] | None]:
    token = websocket.cookies.get(ACCESS_COOKIE)
    if not token:
        return None, None
    try:
        payload = decode_token(token, expected_type="access")
    except pyjwt.PyJWTError:
        return None, None
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == payload.get("sub"))
        .where(User.is_active.is_(True))
    )
    return result.scalar_one_or_none(), payload


async def _load_log_source(db: AsyncSession, log_source_id: str) -> LogSource | None:
    result = await db.execute(
        select(LogSource).options(selectinload(LogSource.agent)).where(LogSource.id == log_source_id)
    )
    return result.scalar_one_or_none()


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket, db: AsyncSession = Depends(get_db)) -> None:
    user, payload = await _authenticate(websocket, db)
    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    manager = get_tail_manager()
    subscriptions: dict[str, Subscription] = {}

    async def teardown(sub_id: str, sub: Subscription) -> None:
        if sub.forward_task is not None:
            sub.forward_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sub.forward_task
        await manager.unsubscribe(sub.session, sub.queue)

    async def reauth_watchdog() -> None:
        exp = payload.get("exp") if payload else None
        if not exp:
            return
        delay = max(0.0, exp - time.time())
        await asyncio.sleep(delay)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "reauth_required"})
            await websocket.close(code=4401)

    watchdog_task = asyncio.create_task(reauth_watchdog())

    async def forward_events(sub_id: str, sub: Subscription) -> None:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=FILTER_DEBOUNCE_SECONDS)
                except asyncio.TimeoutError:
                    event = None

                if isinstance(event, TailLine):
                    if sub.filter_expression:
                        sub.filter_dirty = True
                    else:
                        await websocket.send_json({"type": "line", "subscription_id": sub_id, "text": event.text})
                elif isinstance(event, TailError):
                    await websocket.send_json({"type": "error", "subscription_id": sub_id, "message": event.message})
                elif isinstance(event, TailClosed):
                    await websocket.send_json({"type": "closed", "subscription_id": sub_id, "reason": event.reason})
                    return

                if sub.filter_expression and sub.filter_dirty:
                    sub.filter_dirty = False
                    results, error = await run_grep(list(sub.session.buffer), sub.filter_expression)
                    if error:
                        await websocket.send_json({"type": "filter_error", "subscription_id": sub_id, "message": error})
                    else:
                        await websocket.send_json(
                            {
                                "type": "filtered_snapshot",
                                "subscription_id": sub_id,
                                "lines": [
                                    {
                                        "line_no": r.line_no,
                                        "text": r.text,
                                        "is_match": r.is_match,
                                        "is_separator": r.is_separator,
                                    }
                                    for r in results
                                ],
                            }
                        )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("error forwarding events for subscription %s", sub_id)

    async def handle_subscribe(raw: dict[str, Any]) -> None:
        req_id = raw.get("req_id")
        log_source_id = raw.get("log_source_id")
        client_resolved_path = raw.get("resolved_path")

        if not await has_permission(db, user, LOG_VIEW):
            await websocket.send_json({"type": "error", "req_id": req_id, "message": "insufficient permissions"})
            return

        log_source = await _load_log_source(db, log_source_id) if log_source_id else None
        if log_source is None:
            await websocket.send_json({"type": "error", "req_id": req_id, "message": "log source not found"})
            return

        agent = log_source.agent
        if log_source.mode == "exact_path":
            target_path = client_resolved_path or log_source.path_or_pattern
        elif log_source.mode == "journal":
            # Deterministic like exact_path — always resolves to itself, no
            # client-side pattern-match step needed.
            target_path = client_resolved_path or make_journal_path(log_source.path_or_pattern)
        elif log_source.mode == "docker":
            # Deterministic too — a docker source names exactly one
            # container, same non-pattern-matching category as journal.
            target_path = client_resolved_path or make_docker_path(log_source.path_or_pattern)
        elif client_resolved_path:
            target_path = client_resolved_path
        else:
            await websocket.send_json(
                {"type": "error", "req_id": req_id, "message": "resolved_path is required for glob/regex log sources"}
            )
            return

        try:
            session, queue, backfill = await manager.subscribe(agent.id, target_path)
        except Exception as exc:  # noqa: BLE001 - surfaced to the client, not a server crash
            await websocket.send_json({"type": "error", "req_id": req_id, "message": str(exc)})
            return

        if session.subscriber_count == 1:
            # This subscribe call is what started the underlying TailSession
            # (as opposed to piggy-backing on one someone else already has
            # open) — that's the moment worth recording, not every viewer.
            await audit_record(
                db,
                user_id=user.id,
                event_type="tail_started",
                target_type="agent",
                target_id=agent.id,
                detail={"path": target_path, "log_source_id": log_source_id},
            )

        sub_id = secrets.token_urlsafe(8)
        sub = Subscription(session, queue)
        subscriptions[sub_id] = sub

        await websocket.send_json(
            {"type": "subscribed", "req_id": req_id, "subscription_id": sub_id, "resolved_path": target_path}
        )
        await websocket.send_json({"type": "backfill", "subscription_id": sub_id, "lines": backfill})
        sub.forward_task = asyncio.create_task(forward_events(sub_id, sub))

    async def handle_unsubscribe(raw: dict[str, Any]) -> None:
        sub_id = raw.get("subscription_id")
        sub = subscriptions.pop(sub_id, None)
        if sub is not None:
            await teardown(sub_id, sub)

    async def handle_set_filter(raw: dict[str, Any]) -> None:
        sub_id = raw.get("subscription_id")
        sub = subscriptions.get(sub_id)
        if sub is None:
            return
        expression = (raw.get("expression") or "").strip()
        if not expression:
            await handle_clear_filter(raw)
            return
        sub.filter_expression = expression
        sub.filter_dirty = True

    async def handle_clear_filter(raw: dict[str, Any]) -> None:
        sub_id = raw.get("subscription_id")
        sub = subscriptions.get(sub_id)
        if sub is None:
            return
        sub.filter_expression = None
        sub.filter_dirty = False
        # Restore the plain live view from the current buffer so the client
        # doesn't have a gap between the last filtered snapshot and now.
        await websocket.send_json(
            {"type": "backfill", "subscription_id": sub_id, "lines": list(sub.session.buffer)}
        )

    try:
        while True:
            try:
                raw = await websocket.receive_json()
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid JSON"})
                continue

            msg_type = raw.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "subscribe":
                await handle_subscribe(raw)
            elif msg_type == "unsubscribe":
                await handle_unsubscribe(raw)
            elif msg_type == "set_filter":
                await handle_set_filter(raw)
            elif msg_type == "clear_filter":
                await handle_clear_filter(raw)
            else:
                await websocket.send_json({"type": "error", "message": f"unknown message type: {msg_type!r}"})
    except WebSocketDisconnect:
        pass
    finally:
        watchdog_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog_task
        for sub_id, sub in list(subscriptions.items()):
            await teardown(sub_id, sub)
