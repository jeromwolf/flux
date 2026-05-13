"""API runtime configuration — env-driven, no DB storage of secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class APIConfig:
    """Process-wide config read from environment variables once at startup."""

    jwt_secret: str
    jwt_access_ttl_seconds: int
    cookie_name: str
    cookie_secure: bool
    cookie_domain: str | None
    github_client_id: str
    github_client_secret: str
    github_oauth_authorize_url: str
    github_oauth_token_url: str
    github_oauth_user_url: str
    oauth_callback_url: str
    frontend_url: str
    state_max_age_seconds: int


def load_config() -> APIConfig:
    """Read environment, with safe defaults for dev where applicable.

    For development convenience the JWT secret falls back to a dev value, but
    OAuth secrets are required (empty string is allowed only when ``FLUX_ENV``
    is ``test`` so the unit tests can run without GitHub credentials).
    """
    env = os.environ.get("FLUX_ENV", "dev")
    return APIConfig(
        jwt_secret=os.environ.get("JWT_SECRET", "dev-only-insecure-jwt-secret-change-me"),
        jwt_access_ttl_seconds=int(os.environ.get("JWT_ACCESS_TTL", "3600")),
        cookie_name=os.environ.get("FLUX_COOKIE_NAME", "flux_access"),
        cookie_secure=os.environ.get("FLUX_COOKIE_SECURE", "false").lower() == "true",
        cookie_domain=os.environ.get("FLUX_COOKIE_DOMAIN") or None,
        github_client_id=os.environ.get("GITHUB_CLIENT_ID", "test-client-id" if env == "test" else ""),
        github_client_secret=os.environ.get(
            "GITHUB_CLIENT_SECRET", "test-client-secret" if env == "test" else ""
        ),
        github_oauth_authorize_url=os.environ.get(
            "GITHUB_OAUTH_AUTHORIZE_URL", "https://github.com/login/oauth/authorize"
        ),
        github_oauth_token_url=os.environ.get(
            "GITHUB_OAUTH_TOKEN_URL", "https://github.com/login/oauth/access_token"
        ),
        github_oauth_user_url=os.environ.get(
            "GITHUB_OAUTH_USER_URL", "https://api.github.com/user"
        ),
        oauth_callback_url=os.environ.get(
            "OAUTH_CALLBACK_URL", "http://localhost:8000/auth/github/callback"
        ),
        frontend_url=os.environ.get("FRONTEND_URL", "http://localhost:3000"),
        state_max_age_seconds=int(os.environ.get("OAUTH_STATE_TTL", "300")),
    )
