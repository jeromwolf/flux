"""Tests for /agents/* routes — auth gating, CRUD, tenant isolation, halt/resume."""

from __future__ import annotations

import os

import pytest


VALID_YAML = """\
name: news-bot
description: Test agent
model: claude-haiku
budget:
  per_run: 0.10
  daily: 1.00
  monthly: 10.00
tools:
  - web_search
system_prompt: "You are a helpful assistant."
user_prompt: "Hello!"
"""

INVALID_YAML = """\
description: missing name
model: claude-haiku
"""


@pytest.fixture()
def env(monkeypatch, tmp_path):
    db_path = tmp_path / "agents.db"
    monkeypatch.setenv("FLUX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("FLUX_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("FLUX_COOKIE_SECURE", "false")
    return tmp_path


@pytest.fixture()
def client(env):
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
        yield c


def _login(client, monkeypatch, *, github_id: int, login: str) -> None:
    """Drive the OAuth flow with a stubbed exchange so the client gets a JWT."""
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
# Auth gating
# ---------------------------------------------------------------------------

def test_agents_without_jwt_returns_401(client):
    assert client.get("/agents").status_code == 401
    assert client.post("/agents", json={
        "name": "x", "yaml_source": VALID_YAML,
    }).status_code == 401


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_create_and_list_agent(client, monkeypatch):
    _login(client, monkeypatch, github_id=1, login="kelly")

    create = client.post("/agents", json={
        "name": "news-bot",
        "description": "demo",
        "yaml_source": VALID_YAML,
    })
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "news-bot"
    assert body["description"] == "demo"

    listing = client.get("/agents")
    assert listing.status_code == 200
    names = [a["name"] for a in listing.json()]
    assert names == ["news-bot"]


def test_create_agent_invalid_yaml_returns_422(client, monkeypatch):
    _login(client, monkeypatch, github_id=1, login="kelly")
    response = client.post("/agents", json={"name": "broken", "yaml_source": INVALID_YAML})
    assert response.status_code == 422


def test_create_agent_duplicate_name_returns_409(client, monkeypatch):
    _login(client, monkeypatch, github_id=1, login="kelly")
    first = client.post("/agents", json={"name": "dup", "yaml_source": VALID_YAML})
    assert first.status_code == 201
    second = client.post("/agents", json={"name": "dup", "yaml_source": VALID_YAML})
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# Tenant isolation — second user can't see first user's agent
# ---------------------------------------------------------------------------

def test_cross_tenant_access_returns_404(client, monkeypatch):
    """User B asking for User A's agent gets 404 (not 403)."""
    # User A creates an agent
    _login(client, monkeypatch, github_id=11, login="alice")
    created = client.post("/agents", json={"name": "secret", "yaml_source": VALID_YAML})
    agent_id = created.json()["id"]

    # User B logs in (overrides cookie via fresh OAuth)
    client.cookies.clear()
    _login(client, monkeypatch, github_id=22, login="bob")

    # B sees an empty list, and direct GET on A's agent is 404
    bob_list = client.get("/agents").json()
    assert bob_list == []
    assert client.get(f"/agents/{agent_id}").status_code == 404
    assert client.delete(f"/agents/{agent_id}").status_code == 404


# ---------------------------------------------------------------------------
# Halt / Resume / Status
# ---------------------------------------------------------------------------

def test_halt_then_resume_toggles_emergency_stop(client, monkeypatch, tmp_path, env):
    # Redirect ~/.flux to a temp dir so halt files land somewhere writable+clean
    fake_home = str(tmp_path / "home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

    _login(client, monkeypatch, github_id=42, login="kelly")
    created = client.post("/agents", json={"name": "halt-bot", "yaml_source": VALID_YAML}).json()
    agent_id = created["id"]
    user_id = created["user_id"]

    halt = client.post(f"/agents/{agent_id}/halt")
    assert halt.status_code == 200
    assert halt.json()["halted"] is True
    halt_file = os.path.join(fake_home, ".flux", "users", user_id, "agents", "halt-bot", "emergency_stop")
    assert os.path.exists(halt_file)

    resume = client.post(f"/agents/{agent_id}/resume")
    assert resume.status_code == 200
    assert resume.json()["halted"] is False
    assert not os.path.exists(halt_file)


def test_run_now_records_queued_then_success(client, monkeypatch, tmp_path):
    """POST /agents/{id}/run queues a Run, BackgroundTasks fill it on success."""
    fake_home = str(tmp_path / "home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

    _login(client, monkeypatch, github_id=42, login="kelly")
    agent = client.post("/agents", json={"name": "run-bot", "yaml_source": VALID_YAML}).json()
    agent_id = agent["id"]

    # Replace the heavy runner with a deterministic fake that doesn't call any LLM.
    from flux.api.services import runner_proxy

    async def fake_execute(*, user_id, agent_name, yaml_source):
        from flux.runner import RunResult
        return RunResult(
            agent_name=agent_name,
            text="hello from fake",
            tool_rounds=1,
            input_tokens=120,
            output_tokens=80,
            cost_usd=0.0042,
            duration_seconds=0.5,
            error=None,
            timestamp="2026-05-12T08:00:00",
        )
    monkeypatch.setattr(runner_proxy, "execute_agent", fake_execute)
    # Also patch the symbol bound in the router module
    from flux.api.routers import agents as agents_router
    monkeypatch.setattr(agents_router, "execute_agent", fake_execute)

    # Triggering the run returns 202 with a 'queued' Run row.
    response = client.post(f"/agents/{agent_id}/run")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    run_id = body["id"]

    # TestClient runs BackgroundTasks before returning, so by here it's done.
    runs = client.get(f"/agents/{agent_id}/runs").json()
    completed = next(r for r in runs if r["id"] == run_id)
    assert completed["status"] == "success"
    assert completed["input_tokens"] == 120
    assert completed["output_tokens"] == 80
    assert float(completed["cost_usd"]) == pytest.approx(0.0042)
    assert completed["finished_at"] is not None


def test_run_now_records_error_when_runner_returns_error(client, monkeypatch, tmp_path):
    fake_home = str(tmp_path / "home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

    _login(client, monkeypatch, github_id=42, login="kelly")
    agent = client.post("/agents", json={"name": "err-bot", "yaml_source": VALID_YAML}).json()

    async def fake_execute(*, user_id, agent_name, yaml_source):
        from flux.runner import RunResult
        return RunResult(
            agent_name=agent_name, error="Budget exceeded: $0.11/$0.10",
            timestamp="2026-05-12T08:00:00",
        )
    from flux.api.routers import agents as agents_router
    monkeypatch.setattr(agents_router, "execute_agent", fake_execute)

    client.post(f"/agents/{agent['id']}/run")
    runs = client.get(f"/agents/{agent['id']}/runs").json()
    last = runs[0]
    assert last["status"] == "budget_exceeded"
    assert "Budget exceeded" in last["error"]


def test_run_now_cross_tenant_returns_404(client, monkeypatch):
    _login(client, monkeypatch, github_id=1, login="a")
    a = client.post("/agents", json={"name": "a-bot", "yaml_source": VALID_YAML}).json()
    client.cookies.clear()
    _login(client, monkeypatch, github_id=2, login="b")
    assert client.post(f"/agents/{a['id']}/run").status_code == 404


def test_status_returns_heartbeat_and_budget(client, monkeypatch, tmp_path):
    import json

    fake_home = str(tmp_path / "home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

    _login(client, monkeypatch, github_id=42, login="kelly")
    created = client.post("/agents", json={"name": "s-bot", "yaml_source": VALID_YAML}).json()
    agent_id = created["id"]
    user_id = created["user_id"]

    # Seed disk state
    data_dir = os.path.join(fake_home, ".flux", "users", user_id, "agents", "s-bot")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "heartbeat.json"), "w") as f:
        json.dump({"total_runs": 7, "consecutive_failures": 0}, f)
    with open(os.path.join(data_dir, "budget_state.json"), "w") as f:
        json.dump({"daily_cost": 0.123, "monthly_cost": 1.45}, f)

    response = client.get(f"/agents/{agent_id}/status")
    assert response.status_code == 200
    body = response.json()
    assert body["heartbeat"]["total_runs"] == 7
    assert body["budget"]["daily_cost"] == 0.123
    assert body["halted"] is False
