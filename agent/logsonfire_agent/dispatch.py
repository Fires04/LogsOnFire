"""Handles messages the server sends down /ws/agent: resolve, browse,
start_tail, stop_tail. Each active tail is one asyncio.Task reading from
LocalFileProvider.tail() and pushing tail_line/tail_error/tail_closed
messages back — which paths are actively tailed is entirely server-driven
(start_tail/stop_tail, mirroring the server's own browser-subscriber
refcounting in tailing/manager.py), so this agent never streams a line for
a source nobody's currently watching in the dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import os
import posixpath
from collections.abc import Awaitable, Callable
from typing import Any

from logsonfire_agentcore.base import LogSourceSpec
from logsonfire_agentcore.local import LocalFileProvider

logger = logging.getLogger("logsonfire_agent.dispatch")

SendFn = Callable[[dict], Awaitable[None]]

# How many lines to push as one-shot backfill when a tail starts — the
# server keeps its own much larger ring buffer (log_buffer_max_lines,
# default 20000) fed by the tail_line stream after this; this first batch
# just needs to be "enough to not look empty", not the full history.
BACKFILL_LINES = 200

# Written by install.sh (root-owned, mode 750) alongside a matching
# sudoers(5) NOPASSWD entry naming this exact path with no arguments — the
# agent process itself runs as the unprivileged 'logsonfire-agent' user and
# can neither pip-install into system site-packages nor restart its own
# systemd unit, so a remote "update now" has to go through this narrow,
# fixed-path escalation rather than a broad sudo grant. Hosts enrolled
# before this feature existed won't have it yet — see _handle_self_update.
SELF_UPDATE_SCRIPT = "/usr/local/bin/logsonfire-agent-self-update"


class Dispatcher:
    def __init__(self, send: SendFn) -> None:
        self._send = send
        self._provider = LocalFileProvider()
        self._tails: dict[str, asyncio.Task] = {}

    async def handle(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type == "resolve":
            await self._handle_resolve(message)
        elif msg_type == "browse":
            await self._handle_browse(message)
        elif msg_type == "start_tail":
            await self._handle_start_tail(message)
        elif msg_type == "stop_tail":
            await self._handle_stop_tail(message)
        elif msg_type == "list_units":
            await self._handle_list_units(message)
        elif msg_type == "list_containers":
            await self._handle_list_containers(message)
        elif msg_type == "self_update":
            await self._handle_self_update(message)
        elif msg_type == "ping":
            await self._send({"type": "pong"})
        else:
            logger.warning("server sent unknown message type: %r", msg_type)

    async def _handle_resolve(self, message: dict) -> None:
        req_id = message.get("req_id")
        spec_dict = message.get("log_source") or {}
        spec = LogSourceSpec(
            mode=spec_dict.get("mode", ""),
            path_or_pattern=spec_dict.get("path_or_pattern", ""),
            regex_base_dir=spec_dict.get("regex_base_dir"),
        )
        try:
            files, truncated = await self._provider.resolve_sources(spec)
        except Exception as exc:  # noqa: BLE001 - reported to the server, not a crash
            await self._send(
                {"type": "resolve_result", "req_id": req_id, "files": [], "truncated": False, "error": str(exc)}
            )
            return

        warning = next((f.warning for f in files if f.warning), None)
        await self._send(
            {
                "type": "resolve_result",
                "req_id": req_id,
                "files": [{"path": f.path, "size": f.size, "mtime": f.mtime} for f in files],
                "truncated": truncated,
                "warning": warning,
            }
        )

    async def _handle_browse(self, message: dict) -> None:
        req_id = message.get("req_id")
        path = message.get("path")

        try:
            target = path or await self._provider.default_browse_path()
        except Exception as exc:  # noqa: BLE001
            await self._send(
                {"type": "browse_result", "req_id": req_id, "path": path or "/", "parent": None, "entries": [],
                 "truncated": False, "error": str(exc)}
            )
            return

        # Computed unconditionally, same as the old server-side browse
        # handler used to (see FiresLog's CLAUDE.md gotcha) — a directory
        # that fails to list still needs a `parent` so the file picker's
        # "Up" button keeps working when it's needed most.
        normalized = target.rstrip("/") or "/"
        parent = posixpath.dirname(normalized) if normalized != "/" else None

        try:
            entries, truncated = await self._provider.list_directory(target)
        except Exception as exc:  # noqa: BLE001
            await self._send(
                {"type": "browse_result", "req_id": req_id, "path": normalized, "parent": parent, "entries": [],
                 "truncated": False, "error": str(exc)}
            )
            return

        await self._send(
            {
                "type": "browse_result",
                "req_id": req_id,
                "path": normalized,
                "parent": parent,
                "entries": [
                    {
                        "name": e.name, "path": e.path, "is_dir": e.is_dir, "size": e.size,
                        "mtime": e.mtime, "permissions": e.permissions, "readable": e.readable,
                    }
                    for e in entries
                ],
                "truncated": truncated,
            }
        )

    async def _handle_list_units(self, message: dict) -> None:
        req_id = message.get("req_id")
        try:
            units = await self._provider.list_journal_units()
        except Exception as exc:  # noqa: BLE001 - reported to the server, not a crash
            await self._send({"type": "list_units_result", "req_id": req_id, "units": [], "error": str(exc)})
            return
        await self._send({"type": "list_units_result", "req_id": req_id, "units": units})

    async def _handle_list_containers(self, message: dict) -> None:
        req_id = message.get("req_id")
        try:
            containers = await self._provider.list_docker_containers()
        except Exception as exc:  # noqa: BLE001
            await self._send({"type": "list_containers_result", "req_id": req_id, "containers": [], "error": str(exc)})
            return
        await self._send({"type": "list_containers_result", "req_id": req_id, "containers": containers})

    async def _handle_self_update(self, message: dict) -> None:
        """Runs the equivalent of an operator SSH-ing in and re-running
        upgrade.sh by hand — see SELF_UPDATE_SCRIPT's docstring for why this
        needs a narrow sudo escalation rather than running as this process's
        own (unprivileged) user. Fire-and-forget past the initial ack: the
        upgrade script's own `systemctl restart` (run by upgrade.sh, same as
        a manual upgrade) is very likely to kill this very process, so there
        is no "it finished" message to wait for here — the fresh process's
        next `hello` (with a bumped agent_version) is the real confirmation,
        already surfaced via the existing agent-version-mismatch UI."""
        req_id = message.get("req_id")
        if not os.path.exists(SELF_UPDATE_SCRIPT):
            await self._send(
                {
                    "type": "self_update_result", "req_id": req_id, "started": False,
                    "error": "Remote update isn't set up on this host yet — re-run install.sh once to enable it.",
                }
            )
            return
        await self._send({"type": "self_update_result", "req_id": req_id, "started": True})
        try:
            await asyncio.create_subprocess_exec(
                "sudo", "-n", SELF_UPDATE_SCRIPT,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:  # noqa: BLE001 - already acked "started"; a missing reconnect is the real signal
            logger.exception("failed to launch self-update")

    async def _handle_start_tail(self, message: dict) -> None:
        req_id = message.get("req_id")
        path = message["resolved_path"]

        try:
            backfill = await self._provider.read_tail(path, BACKFILL_LINES)
        except Exception as exc:  # noqa: BLE001
            await self._send({"type": "tail_backfill", "req_id": req_id, "lines": [], "error": str(exc)})
            return

        await self._send({"type": "tail_backfill", "req_id": req_id, "lines": backfill})

        if path not in self._tails:
            self._tails[path] = asyncio.create_task(self._follow(path), name=f"tail:{path}")

    async def _handle_stop_tail(self, message: dict) -> None:
        path = message["resolved_path"]
        task = self._tails.pop(path, None)
        if task is not None:
            task.cancel()

    async def _follow(self, path: str) -> None:
        try:
            async for line in self._provider.tail(path):
                await self._send({"type": "tail_line", "resolved_path": path, "text": line})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the server, not a crash
            await self._send({"type": "tail_error", "resolved_path": path, "message": str(exc)})
        finally:
            self._tails.pop(path, None)
            await self._send({"type": "tail_closed", "resolved_path": path, "reason": "stopped"})

    async def stop_all(self) -> None:
        """Called when the connection drops — the running tail tasks are
        cancelled, but nothing is sent about it (there's no connection to
        send it over; the server notices the disconnect itself and marks
        every session it owned closed, see agents/service.py's
        mark_disconnected)."""
        for task in self._tails.values():
            task.cancel()
        self._tails.clear()
