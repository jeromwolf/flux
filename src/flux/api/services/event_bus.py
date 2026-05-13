"""Per-agent in-memory pub/sub used by WebSocket subscribers.

The web API and the background "Run Now" task share one process, so a simple
dict-of-asyncio.Queue is enough. Each WebSocket subscriber gets its own queue;
``publish`` enqueues a copy of the event to every active subscriber for the
given agent_id (fan-out). Disconnected/full queues are dropped silently.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any


_QUEUE_MAX = 256  # back-pressure cap per subscriber


class EventBus:
    """Process-wide singleton. Instances of this class are stateless wrappers
    over module-level state, but we keep an explicit class so tests can build
    isolated buses if needed.
    """

    _subscribers: dict[str, set[asyncio.Queue]] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def subscribe(cls, agent_id: uuid.UUID | str) -> asyncio.Queue:
        key = str(agent_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        async with cls._lock:
            cls._subscribers.setdefault(key, set()).add(queue)
        return queue

    @classmethod
    async def unsubscribe(cls, agent_id: uuid.UUID | str, queue: asyncio.Queue) -> None:
        key = str(agent_id)
        async with cls._lock:
            subs = cls._subscribers.get(key)
            if subs is None:
                return
            subs.discard(queue)
            if not subs:
                cls._subscribers.pop(key, None)

    @classmethod
    async def publish(cls, agent_id: uuid.UUID | str, event: dict[str, Any]) -> None:
        key = str(agent_id)
        async with cls._lock:
            subs = list(cls._subscribers.get(key, ()))
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow subscriber - drop oldest to make room, then enqueue.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except asyncio.QueueEmpty:
                    pass

    @classmethod
    def subscriber_count(cls, agent_id: uuid.UUID | str) -> int:
        return len(cls._subscribers.get(str(agent_id), ()))

    @classmethod
    async def reset(cls) -> None:
        """Test helper — drop all subscribers."""
        async with cls._lock:
            cls._subscribers.clear()
