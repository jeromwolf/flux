"""FastAPI dependencies: config, current user, request session helpers."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from flux.api.auth import decode_access_token
from flux.api.config import APIConfig, load_config
from flux.api.db import get_session
from flux.api.models import User
from flux.api.repositories import UserRepository


# Cached at module level — config is immutable after process start.
_config: APIConfig | None = None


def get_config() -> APIConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


ConfigDep = Annotated[APIConfig, Depends(get_config)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    config: ConfigDep,
    session: SessionDep,
    flux_access: Annotated[str | None, Cookie()] = None,
) -> User:
    """Resolve the User from the access-token cookie.

    Raises 401 if missing, expired, malformed, or pointing at a non-existent user.
    """
    if not flux_access:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing access token")

    payload = decode_access_token(config, flux_access)
    if payload is None or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid access token")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed subject")

    user = await UserRepository(session).get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
