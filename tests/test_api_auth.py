"""Tests for /auth/* routes (GitHub OAuth + JWT + /me + /logout)."""

from __future__ import annotations

import os

import pytest


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Test env: SQLite DB, OAuth in 'test' mode with known dummy creds."""
    db_path = tmp_path / "auth.db"
    monkeypatch.setenv("FLUX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("FLUX_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-cid")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OAUTH_CALLBACK_URL", "http://localhost:8000/auth/github/callback")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    monkeypatch.setenv("FLUX_COOKIE_SECURE", "false")
    return tmp_path


@pytest.fixture()
def client(env):
    """Build a TestClient with a clean app (lifespan creates the engine)."""
    from fastapi.testclient import TestClient

    # Reset cached config so env vars take effect
    from flux.api import deps as _deps
    _deps._config = None

    from flux.api.app import create_app
    app = create_app()
    with TestClient(app) as c:
        # Run the migration against the SQLite file used by the app
        from sqlalchemy import create_engine
        from flux.api.db import Base
        sync_url = os.environ["FLUX_DATABASE_URL"].replace("sqlite+aiosqlite", "sqlite")
        engine = create_engine(sync_url)
        Base.metadata.create_all(engine)
        engine.dispose()
        yield c


# ---------------------------------------------------------------------------
# /auth/github/login
# ---------------------------------------------------------------------------

def test_github_login_redirects_and_sets_state_cookie(client):
    response = client.get("/auth/github/login", follow_redirects=False)
    assert response.status_code == 302
    assert "github.com/login/oauth/authorize" in response.headers["location"]
    assert "client_id=test-cid" in response.headers["location"]
    assert "state=" in response.headers["location"]
    # State cookie must be set so callback can verify
    assert "flux_oauth_state" in response.cookies


# ---------------------------------------------------------------------------
# /auth/github/callback — state mismatch
# ---------------------------------------------------------------------------

def test_callback_state_mismatch_returns_400(client):
    # Get a real state first
    login = client.get("/auth/github/login", follow_redirects=False)
    real_state = login.cookies["flux_oauth_state"]
    # Send a different state in the query
    response = client.get(
        "/auth/github/callback",
        params={"code": "ignored", "state": "wrong-state"},
        cookies={"flux_oauth_state": real_state},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "state mismatch" in response.text


def test_callback_missing_params_returns_400(client):
    response = client.get("/auth/github/callback", follow_redirects=False)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# /auth/github/callback — happy path (mock GitHub exchange)
# ---------------------------------------------------------------------------

def test_callback_happy_path_issues_jwt_and_redirects(client, monkeypatch):
    """Stub out the GitHub round-trip and assert the JWT cookie + redirect."""
    from flux.api.routers import auth as auth_router

    async def fake_exchange(config, code, client=None):
        return {
            "github_id": 9999,
            "github_login": "kelly",
            "email": "k@flux.ai.kr",
            "avatar_url": "http://gh/avatar.png",
        }
    monkeypatch.setattr(auth_router, "exchange_github_code", fake_exchange)

    login = client.get("/auth/github/login", follow_redirects=False)
    state = login.cookies["flux_oauth_state"]

    response = client.get(
        "/auth/github/callback",
        params={"code": "ok-code", "state": state},
        cookies={"flux_oauth_state": state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/dashboard"
    # Access cookie installed
    assert "flux_access" in response.cookies


# ---------------------------------------------------------------------------
# /auth/me — 401 without JWT, 200 with JWT
# ---------------------------------------------------------------------------

def test_me_without_jwt_returns_401(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_with_valid_jwt_returns_profile(client, monkeypatch):
    """After a successful OAuth flow, /auth/me returns the user."""
    from flux.api.routers import auth as auth_router

    async def fake_exchange(config, code, client=None):
        return {
            "github_id": 12345,
            "github_login": "alice",
            "email": None,
            "avatar_url": None,
        }
    monkeypatch.setattr(auth_router, "exchange_github_code", fake_exchange)

    login = client.get("/auth/github/login", follow_redirects=False)
    state = login.cookies["flux_oauth_state"]
    callback = client.get(
        "/auth/github/callback",
        params={"code": "ok", "state": state},
        cookies={"flux_oauth_state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 302
    # TestClient persists cookies on its session — use them on /me
    me = client.get("/auth/me")
    assert me.status_code == 200
    profile = me.json()
    assert profile["github_login"] == "alice"
    assert profile["github_id"] == 12345


def test_logout_clears_cookie(client, monkeypatch):
    from flux.api.routers import auth as auth_router

    async def fake_exchange(config, code, client=None):
        return {"github_id": 1, "github_login": "u", "email": None, "avatar_url": None}
    monkeypatch.setattr(auth_router, "exchange_github_code", fake_exchange)
    login = client.get("/auth/github/login", follow_redirects=False)
    state = login.cookies["flux_oauth_state"]
    client.get(
        "/auth/github/callback",
        params={"code": "ok", "state": state},
        cookies={"flux_oauth_state": state},
        follow_redirects=False,
    )
    assert client.get("/auth/me").status_code == 200

    logout = client.post("/auth/logout")
    assert logout.status_code == 204
    # Cookie removed -> /me again 401
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401
