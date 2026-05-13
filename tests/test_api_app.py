"""Tests for the FastAPI application + /healthz."""

from __future__ import annotations

import os

import pytest


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient with FLUX_DATABASE_URL pointed at a temp SQLite file.

    The lifespan handler creates the engine using that env var.
    """
    db_path = tmp_path / "flux-test.db"
    monkeypatch.setenv("FLUX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    # Import lazily so the env var is in place before app.py is touched
    from fastapi.testclient import TestClient
    from flux.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_healthz_returns_ok_and_version(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    # SQLite is reachable -> database should report "ok"
    assert body["database"] == "ok"


def test_unknown_route_returns_404(client):
    response = client.get("/this-does-not-exist")
    assert response.status_code == 404


def test_openapi_schema_served(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Flux API"
    # /healthz must be documented
    assert "/healthz" in schema["paths"]
