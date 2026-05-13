"""Tail an agent's on-disk ``agent.log`` and publish new lines onto the EventBus.

Poll-based on purpose: log files can be rotated, truncated, or removed by the
CLI/Watchdog, and a stat-based loop handles those cases without inotify.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from flux.api.services.event_bus import EventBus


_POLL_INTERVAL_SECONDS = 1.0


async def tail_agent_log(
    *,
    agent_id: uuid.UUID,
    log_path: str,
    stop_event: asyncio.Event,
) -> None:
    """Poll the file every second and publish any new lines until ``stop_event`` is set.

    Uses inode + position tracking so truncation (logrotate-style) is detected
    and the read pointer resets cleanly.
    """
    inode: int | None = None
    pos = 0

    while not stop_event.is_set():
        try:
            stat = os.stat(log_path)
        except FileNotFoundError:
            await _sleep_or_stop(stop_event)
            continue

        # Detect rotation or first open
        if inode != stat.st_ino or pos > stat.st_size:
            inode = stat.st_ino
            pos = 0

        if stat.st_size > pos:
            chunk = await asyncio.to_thread(_read_chunk, log_path, pos, stat.st_size)
            new_pos = pos + len(chunk.encode("utf-8", errors="replace"))
            for line in chunk.splitlines():
                if not line:
                    continue
                await EventBus.publish(agent_id, {"type": "log", "msg": line})
            pos = new_pos

        await _sleep_or_stop(stop_event)


async def _sleep_or_stop(stop_event: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=_POLL_INTERVAL_SECONDS)
    except asyncio.TimeoutError:
        pass


def _read_chunk(path: str, start: int, end: int) -> str:
    """Read ``[start, end)`` bytes from the file as utf-8 (errors replaced)."""
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(end - start)
    return data.decode("utf-8", errors="replace")
