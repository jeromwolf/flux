"""Tests for CORS middleware and slowapi rate limiting on the FastAPI app."""

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


@pytest.fixture()
def env(monkeypatch, tmp_path):
    db_path = tmp_path / "mw.db"
    monkeypatch.setenv("FLUX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("FLUX_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    monkeypatch.setenv("FLUX_COOKIE_SECURE", "false")
    # Pin CORS to a single allowed origin so we can assert the negative case.
    monkeypatch.setenv("FLUX_CORS_ORIGINS", "http://localhost:3000")
    return tmp_path


@pytest.fixture()
def client(env):
    """Reset cached config + limiter so each test gets a clean rate budget."""
    from fastapi.testclient import TestClient

    from flux.api import deps as _deps
    _deps._config = None

    # Fresh limiter state per test — slowapi keeps an in-memory bucket that
    # would otherwise bleed across tests sharing the same key.
    from flux.api.rate_limit import limiter
    limiter.reset()

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
# CORS
# ---------------------------------------------------------------------------

def test_cors_allows_configured_origin(client):
    """OPTIONS preflight from the configured frontend returns ACAO."""
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORSMiddleware short-circuits preflight with 200.
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_blocks_unconfigured_origin(client):
    """Preflight from an origin not in FLUX_CORS_ORIGINS does NOT get ACAO."""
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Starlette returns 400 for a disallowed preflight; either way no ACAO header.
    assert "access-control-allow-origin" not in response.headers


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------

def test_rate_limit_run_endpoint(client, monkeypatch, tmp_path):
    """Sixth /agents/{id}/run within a minute trips slowapi → 429."""
    fake_home = str(tmp_path / "home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

    _login(client, monkeypatch, github_id=42, login="kelly")
    agent = client.post("/agents", json={"name": "rl-bot", "yaml_source": VALID_YAML}).json()
    agent_id = agent["id"]

    # Stub the runner so we never actually invoke the LLM.
    async def fake_execute(*, user_id, agent_name, yaml_source):
        from flux.runner import RunResult
        return RunResult(
            agent_name=agent_name,
            text="ok",
            tool_rounds=0,
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            duration_seconds=0.0,
            error=None,
            timestamp="2026-05-12T08:00:00",
        )

    from flux.api.routers import agents as agents_router
    monkeypatch.setattr(agents_router, "execute_agent", fake_execute)

    # /agents/{id}/run is limited to 5/minute. First 5 succeed, 6th is 429.
    statuses = [client.post(f"/agents/{agent_id}/run").status_code for _ in range(6)]
    assert statuses[:5] == [202, 202, 202, 202, 202], statuses
    assert statuses[5] == 429, statuses
