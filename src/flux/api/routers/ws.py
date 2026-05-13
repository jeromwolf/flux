"""WebSocket router: live log/heartbeat/run-complete stream per agent.

Path: ``/ws/agents/{agent_id}``

Auth: same ``flux_access`` cookie as REST routes. Unauthenticated or
cross-tenant connections are closed with code 1008 (policy violation), never
3xx or HTTP-style status codes (WebSockets don't have those).

Event shapes::

    {"type": "snapshot", "agent": {...}, "heartbeat": {...}, "halted": bool}
    {"type": "log", "msg": "..."}
    {"type": "heartbeat", "heartbeat": {...}, "halted": bool}
    {"type": "run_complete", "run_id": "...", "status": "success", "cost_usd": 0.014}
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from flux.api.auth import decode_access_token
from flux.api.db import get_sessionmaker
from flux.api.deps import get_config
from flux.api.repositories import AgentRepository, UserRepository
from flux.api.services.event_bus import EventBus
from flux.api.services.log_tailer import tail_agent_log
from flux.api.services.runner_proxy import user_agent_data_dir

router = APIRouter(tags=["ws"])

_HEARTBEAT_POLL_SECONDS = 2.0
_POLICY_VIOLATION = status.WS_1008_POLICY_VIOLATION


async def _resolve_user_and_agent(websocket: WebSocket, agent_id: uuid.UUID):
    """Return (user, agent) if authenticated and authorised; close + return None otherwise."""
    config = get_config()
    token = websocket.cookies.get(config.cookie_name)
    if not token:
        await websocket.close(code=_POLICY_VIOLATION)
        return None, None
    payload = decode_access_token(config, token)
    if payload is None or "sub" not in payload:
        await websocket.close(code=_POLICY_VIOLATION)
        return None, None
    try:
        user_id = uuid.UUID(payload["sub"])
    except (TypeError, ValueError):
        await websocket.close(code=_POLICY_VIOLATION)
        return None, None

    sm = get_sessionmaker()
    async with sm() as session:
        user = await UserRepository(session).get(user_id)
        if user is None:
            await websocket.close(code=_POLICY_VIOLATION)
            return None, None
        agent = await AgentRepository(session).get_for_user(agent_id, user.id)
        if agent is None:
            await websocket.close(code=_POLICY_VIOLATION)
            return None, None
        # Detach from session — caller only needs scalar attributes.
        await session.refresh(agent)
        agent_snapshot = {
            "id": str(agent.id),
            "name": agent.name,
            "status": agent.status,
        }
        return user, agent_snapshot


def _read_heartbeat(data_dir: str) -> dict:
    path = os.path.join(data_dir, "heartbeat.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


async def _poll_heartbeat(*, agent_id: uuid.UUID, data_dir: str, stop_event: asyncio.Event):
    """Push heartbeat updates whenever the snapshot changes."""
    last: dict | None = None
    while not stop_event.is_set():
        current = _read_heartbeat(data_dir)
        halted = os.path.exists(os.path.join(data_dir, "emergency_stop"))
        snapshot = {"heartbeat": current, "halted": halted}
        if snapshot != last:
            await EventBus.publish(agent_id, {"type": "heartbeat", **snapshot})
            last = snapshot
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_HEARTBEAT_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


@router.websocket("/ws/agents/{agent_id}")
async def agent_stream(websocket: WebSocket, agent_id: uuid.UUID) -> None:
    user, agent = await _resolve_user_and_agent(websocket, agent_id)
    if user is None or agent is None:
        return

    await websocket.accept()

    data_dir = user_agent_data_dir(user.id, agent["name"])
    queue = await EventBus.subscribe(agent_id)
    stop_event = asyncio.Event()

    # Initial snapshot so the client doesn't see a blank UI before the first event.
    snapshot = {
        "type": "snapshot",
        "agent": agent,
        "heartbeat": _read_heartbeat(data_dir),
        "halted": os.path.exists(os.path.join(data_dir, "emergency_stop")),
    }
    await websocket.send_json(snapshot)

    log_task = asyncio.create_task(
        tail_agent_log(
            agent_id=agent_id,
            log_path=os.path.join(data_dir, "agent.log"),
            stop_event=stop_event,
        )
    )
    heartbeat_task = asyncio.create_task(
        _poll_heartbeat(agent_id=agent_id, data_dir=data_dir, stop_event=stop_event)
    )
    pump_task = asyncio.create_task(_pump_outbound(websocket, queue, stop_event))

    try:
        # Block until the client disconnects (we don't expect any inbound messages
        # in this MVP; receive_text raises WebSocketDisconnect on close).
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        stop_event.set()
        await EventBus.unsubscribe(agent_id, queue)
        for t in (log_task, heartbeat_task, pump_task):
            t.cancel()
        await asyncio.gather(log_task, heartbeat_task, pump_task, return_exceptions=True)


async def _pump_outbound(
    websocket: WebSocket, queue: asyncio.Queue, stop_event: asyncio.Event
) -> None:
    """Forward queued events from EventBus to the WebSocket."""
    while not stop_event.is_set():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        try:
            await websocket.send_json(event)
        except Exception:
            stop_event.set()
            return
