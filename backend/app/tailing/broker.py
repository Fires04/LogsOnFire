"""In-process pub/sub: fan out events from one TailSession to N WebSocket
subscribers, with bounded per-subscriber queues so one slow browser tab can
never make a TailSession (or other subscribers of it) block or grow without
bound — the oldest buffered event is dropped instead.
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

QUEUE_MAX_SIZE = 1000


@dataclass
class TailLine:
    text: str


@dataclass
class TailError:
    message: str


@dataclass
class TailClosed:
    reason: str  # "rotated" | "agent_disconnected" | "stopped" | "error"


TailEvent = TailLine | TailError | TailClosed


class LineBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[TailEvent]] = set()

    def subscribe(self) -> "asyncio.Queue[TailEvent]":
        queue: asyncio.Queue[TailEvent] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[TailEvent]") -> None:
        self._subscribers.discard(queue)

    def publish(self, event: TailEvent) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop the oldest buffered event to make room
                # rather than blocking the (single, shared) producer.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)
