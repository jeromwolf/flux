"""WebSocket tests: auth, tenant isolation, snapshot + run_complete fan-out."""

from __future__ import annotations

import os

import pytest
from starlette.websockets import WebSocketDisconnect


VALID_YAML = """\
name: ws-bot
description: Test agent
model: claude-haiku
budget:
  per_run: 0.10
  daily: 1.00
  monthly: 10.00
tools:
  - web_search
system_prompt: "Hi."
user_prompt: "Hello!"
"""


@pytest.fixture()
def env(monkeypatch, tmp_path):
    db_path = tmp_path / "ws.db"
    monkeypatch.setenv("FLUX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("FLUX_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("FLUX_COOKIE_SECURE", "false")
    return tmp_path


@pytest.fixture()
def client(env, monkeypatch):
    from fastapi.testclient import TestClient
    from flux.api import deps as _deps
    _deps._config = None
    from flux.api.app import create_app
    app = create_app()
    with TestClient(app) as c:
        from sqlalchemy import create_engine
        from flux.api.db import Base
        sync_url = os.environ["FLUX_DATABASE_URL"].replace("sqlite+aiosqlite", "sqlite")
        engine = create_engine(sync_url)
        Base.metadata.create_all(engine)
        engine.dispose()
        # Clear in-process EventBus state between tests
        import asyncio
        from flux.api.services.event_bus import EventBus
        asyncio.get_event_loop().run_until_complete(EventBus.reset())
        yield c


def _login(client, monkeypatch, *, github_id: int, login: str):
    from flux.api.routers import auth as auth_router

    async def fake_exchange(config, code, client=None):
        return {"github_id": github_id, "github_login": login, "email": None, "avatar_url": None}
    monkeypatch.setattr(auth_router, "exchange_github_code", fake_exchange)

    resp = client.get("/auth/github/login", follow_redirects=False)
    state = resp.cookies["flux_oauth_state"]
    cb = client.get(
        "/auth/github/callback",
        params={"code": "ok", "state": state},
        cookies={"flux_oauth_state": state},
        follow_redirects=False,
    )
    assert cb.status_code == 302


# ---------------------------------------------------------------------------
# Auth + tenant isolation
# ---------------------------------------------------------------------------

def test_ws_without_auth_is_rejected(client):
    """No cookie -> 1008 policy violation."""
    import uuid as _uuid
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/agents/{_uuid.uuid4()}") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_ws_cross_tenant_is_rejected(client, monkeypatch):
    """User B cannot subscribe to User A's agent."""
    _login(client, monkeypatch, github_id=1, login="alice")
    a = client.post("/agents", json={"name": "a-bot", "yaml_source": VALID_YAML}).json()
    client.cookies.clear()
    _login(client, monkeypatch, github_id=2, login="bob")

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/agents/{a['id']}") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


# ---------------------------------------------------------------------------
# Happy path: snapshot + run_complete fan-out
# ---------------------------------------------------------------------------

def test_ws_owner_gets_snapshot_and_run_complete(client, monkeypatch, tmp_path):
    fake_home = str(tmp_path / "home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

    _login(client, monkeypatch, github_id=42, login="kelly")
    agent = client.post("/agents", json={"name": "ws-bot", "yaml_source": VALID_YAML}).json()
    agent_id = agent["id"]

    # Stub the runner so triggering a run finishes fast and publishes run_complete.
    from flux.api.routers import agents as agents_router

    async def fake_execute(*, user_id, agent_name, yaml_source):
        from flux.runner import RunResult
        return RunResult(
            agent_name=agent_name,
            text="ok",
            tool_rounds=0,
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0001,
            duration_seconds=0.01,
            error=None,
            timestamp="2026-05-13T00:00:00",
        )
    monkeypatch.setattr(agents_router, "execute_agent", fake_execute)

    with client.websocket_connect(f"/ws/agents/{agent_id}") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert snap["agent"]["name"] == "ws-bot"
        assert snap["halted"] is False

        # Trigger a run; the BackgroundTask will publish run_complete after commit.
        resp = client.post(f"/agents/{agent_id}/run")
        assert resp.status_code == 202

        # Drain until we see run_complete (heartbeat snapshots may interleave).
        seen = None
        for _ in range(20):
            event = ws.receive_json()
            if event.get("type") == "run_complete":
                seen = event
                break
        assert seen is not None, "expected a run_complete event"
        assert seen["status"] == "success"
        assert seen["input_tokens"] == 10
        assert seen["output_tokens"] == 5
