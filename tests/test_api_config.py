"""Tests for flux.api.config.load_config — env-driven prod guards."""

from __future__ import annotations

import pytest

from flux.api.config import load_config


# Keys that load_config inspects — we delete them all up-front and re-set the
# subset each test cares about. This avoids cross-test bleed via real shell env.
_ENV_KEYS = (
    "FLUX_ENV",
    "JWT_SECRET",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "FLUX_CORS_ORIGINS",
    "FRONTEND_URL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


# ---------------------------------------------------------------------------
# Prod hardening — JWT_SECRET
# ---------------------------------------------------------------------------

def test_prod_requires_jwt_secret(monkeypatch):
    monkeypatch.setenv("FLUX_ENV", "prod")
    # GitHub creds present so we isolate the JWT failure mode
    monkeypatch.setenv("GITHUB_CLIENT_ID", "x")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "y")
    with pytest.raises(RuntimeError, match="JWT_SECRET must be set in production"):
        load_config()


def test_prod_rejects_dev_fallback(monkeypatch):
    monkeypatch.setenv("FLUX_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "dev-only-insecure-jwt-secret-change-me")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "x")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "y")
    with pytest.raises(RuntimeError, match="must not use the dev fallback"):
        load_config()


def test_prod_rejects_short_secret(monkeypatch):
    monkeypatch.setenv("FLUX_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "short")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "x")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "y")
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        load_config()


def test_prod_accepts_strong_secret(monkeypatch):
    monkeypatch.setenv("FLUX_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("GITHUB_CLIENT_ID", "real-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "real-secret")
    cfg = load_config()
    assert cfg.jwt_secret == "x" * 32
    assert cfg.github_client_id == "real-id"
    assert cfg.github_client_secret == "real-secret"


def test_dev_allows_fallback(monkeypatch):
    # No FLUX_ENV -> defaults to 'dev'. No JWT_SECRET -> fallback applies.
    cfg = load_config()
    assert cfg.jwt_secret == "dev-only-insecure-jwt-secret-change-me"


# ---------------------------------------------------------------------------
# Prod hardening — GitHub OAuth
# ---------------------------------------------------------------------------

def test_prod_requires_github_secrets(monkeypatch):
    monkeypatch.setenv("FLUX_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    # GITHUB_CLIENT_ID intentionally missing (empty)
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "y")
    with pytest.raises(RuntimeError, match="GITHUB_CLIENT_ID must be set in production"):
        load_config()


def test_prod_requires_github_client_secret(monkeypatch):
    monkeypatch.setenv("FLUX_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("GITHUB_CLIENT_ID", "x")
    # GITHUB_CLIENT_SECRET intentionally missing
    with pytest.raises(RuntimeError, match="GITHUB_CLIENT_SECRET must be set in production"):
        load_config()
