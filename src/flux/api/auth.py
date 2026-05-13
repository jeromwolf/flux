"""JWT + OAuth state utilities.

- ``issue_access_token`` / ``decode_access_token``  -> JWT (HS256)
- ``make_state_token`` / ``read_state_token``       -> short-lived signed CSRF state
- ``exchange_github_code``                          -> code -> access token -> user
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jose import JWTError, jwt

from flux.api.config import APIConfig


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

_JWT_ALG = "HS256"


def issue_access_token(config: APIConfig, *, user_id: uuid.UUID, github_id: int) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "gid": github_id,
        "iat": now,
        "exp": now + config.jwt_access_ttl_seconds,
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=_JWT_ALG)


def decode_access_token(config: APIConfig, token: str) -> Optional[dict]:
    """Return payload or None on any failure (expired / bad signature / format)."""
    try:
        return jwt.decode(token, config.jwt_secret, algorithms=[_JWT_ALG])
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# OAuth state token (CSRF + timed)
# ---------------------------------------------------------------------------

_STATE_SALT = "flux-oauth-state-v1"


def _state_serializer(config: APIConfig) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=config.jwt_secret, salt=_STATE_SALT)


def make_state_token(config: APIConfig, *, nonce: str | None = None) -> str:
    payload = {"n": nonce or uuid.uuid4().hex}
    return _state_serializer(config).dumps(payload)


def read_state_token(config: APIConfig, token: str) -> Optional[dict]:
    """Return parsed state dict or None if expired/tampered."""
    try:
        return _state_serializer(config).loads(token, max_age=config.state_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None


# ---------------------------------------------------------------------------
# GitHub OAuth exchange
# ---------------------------------------------------------------------------

class GitHubOAuthError(Exception):
    """Raised when the OAuth code exchange or user fetch fails."""


async def exchange_github_code(
    config: APIConfig,
    code: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Exchange an OAuth code for a GitHub user profile.

    Returns dict with: github_id, github_login, email, avatar_url.

    Raises GitHubOAuthError on any non-2xx or schema mismatch.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        # 1) exchange code -> access_token
        token_resp = await client.post(
            config.github_oauth_token_url,
            data={
                "client_id": config.github_client_id,
                "client_secret": config.github_client_secret,
                "code": code,
                "redirect_uri": config.oauth_callback_url,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise GitHubOAuthError(f"token exchange returned {token_resp.status_code}")
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise GitHubOAuthError(f"no access_token in response: {token_data}")

        # 2) fetch user profile
        user_resp = await client.get(
            config.github_oauth_user_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if user_resp.status_code != 200:
            raise GitHubOAuthError(f"user fetch returned {user_resp.status_code}")
        u = user_resp.json()

        if not isinstance(u, dict) or "id" not in u or "login" not in u:
            raise GitHubOAuthError(f"unexpected user payload: {u}")

        return {
            "github_id": int(u["id"]),
            "github_login": str(u["login"]),
            "email": u.get("email"),
            "avatar_url": u.get("avatar_url"),
        }
    finally:
        if owns_client:
            await client.aclose()
