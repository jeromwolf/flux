"""API runtime configuration — env-driven, no DB storage of secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass


_DEV_JWT_FALLBACK = "dev-only-insecure-jwt-secret-change-me"
_PROD_JWT_MIN_LENGTH = 32


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
    cors_origins: list[str]


def _resolve_jwt_secret(env: str) -> str:
    """Resolve JWT_SECRET with prod hardening.

    In production (``FLUX_ENV=prod``):
      * The secret MUST be set (non-empty).
      * It MUST NOT match the dev fallback string.
      * It MUST be at least 32 characters long.

    In any other environment (``dev``, ``test``) the dev fallback is allowed
    so unit tests and local dev work without secrets.
    """
    raw = os.environ.get("JWT_SECRET")
    if env == "prod":
        if not raw:
            raise RuntimeError("JWT_SECRET must be set in production")
        if raw == _DEV_JWT_FALLBACK:
            raise RuntimeError(
                "JWT_SECRET must not use the dev fallback value in production"
            )
        if len(raw) < _PROD_JWT_MIN_LENGTH:
            raise RuntimeError(
                f"JWT_SECRET must be at least {_PROD_JWT_MIN_LENGTH} characters in production"
            )
        return raw
    # dev/test: fall back to known-insecure value if unset
    return raw if raw else _DEV_JWT_FALLBACK


def _resolve_github_secrets(env: str) -> tuple[str, str]:
    """Resolve GitHub OAuth credentials with prod hardening.

    ``test`` env returns dummy credentials so unit tests can drive the OAuth flow.
    ``prod`` env REQUIRES both ``GITHUB_CLIENT_ID`` and ``GITHUB_CLIENT_SECRET``
    to be set to non-empty values; otherwise startup fails fast.
    """
    raw_id = os.environ.get("GITHUB_CLIENT_ID", "")
    raw_secret = os.environ.get("GITHUB_CLIENT_SECRET", "")
    if env == "prod":
        if not raw_id:
            raise RuntimeError("GITHUB_CLIENT_ID must be set in production")
        if not raw_secret:
            raise RuntimeError("GITHUB_CLIENT_SECRET must be set in production")
        return raw_id, raw_secret
    if env == "test":
        return raw_id or "test-client-id", raw_secret or "test-client-secret"
    return raw_id, raw_secret


def _resolve_cors_origins(frontend_url: str) -> list[str]:
    """Resolve allowed CORS origins.

    Defaults to ``[frontend_url]``. Operators can append additional origins via
    ``FLUX_CORS_ORIGINS`` (comma-separated). The frontend URL is always included.
    """
    extra = os.environ.get("FLUX_CORS_ORIGINS", "")
    origins: list[str] = [frontend_url]
    if extra:
        for piece in extra.split(","):
            piece = piece.strip()
            if piece and piece not in origins:
                origins.append(piece)
    return origins


def load_config() -> APIConfig:
    """Read environment, with safe defaults for dev where applicable.

    Production (``FLUX_ENV=prod``) enforces:
      * ``JWT_SECRET`` set, not the dev fallback, ≥ 32 chars.
      * ``GITHUB_CLIENT_ID`` and ``GITHUB_CLIENT_SECRET`` set and non-empty.

    Dev/test environments fall back to insecure defaults so unit tests run
    without real secrets.
    """
    env = os.environ.get("FLUX_ENV", "dev")
    jwt_secret = _resolve_jwt_secret(env)
    github_client_id, github_client_secret = _resolve_github_secrets(env)
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    return APIConfig(
        jwt_secret=jwt_secret,
        jwt_access_ttl_seconds=int(os.environ.get("JWT_ACCESS_TTL", "3600")),
        cookie_name=os.environ.get("FLUX_COOKIE_NAME", "flux_access"),
        cookie_secure=os.environ.get("FLUX_COOKIE_SECURE", "false").lower() == "true",
        cookie_domain=os.environ.get("FLUX_COOKIE_DOMAIN") or None,
        github_client_id=github_client_id,
        github_client_secret=github_client_secret,
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
        frontend_url=frontend_url,
        state_max_age_seconds=int(os.environ.get("OAUTH_STATE_TTL", "300")),
        cors_origins=_resolve_cors_origins(frontend_url),
    )
