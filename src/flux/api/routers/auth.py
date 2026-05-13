"""Authentication routes: GitHub OAuth + JWT cookie issuance.

Flow::

    GET /auth/github/login           -> 302 to GitHub, set state cookie
    GET /auth/github/callback?code,state
                                     -> verify state, exchange code, upsert user,
                                        issue JWT, set flux_access cookie, 302 to frontend
    GET /auth/me                     -> current user profile (401 if no JWT)
    POST /auth/logout                -> clear cookies
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from typing import Annotated

from flux.api.auth import (
    GitHubOAuthError,
    exchange_github_code,
    issue_access_token,
    make_state_token,
    read_state_token,
)
from flux.api.deps import ConfigDep, CurrentUserDep, SessionDep
from flux.api.repositories import UserRepository
from flux.api.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_STATE_COOKIE = "flux_oauth_state"


def _set_access_cookie(response: Response, *, name: str, token: str, max_age: int, secure: bool, domain: str | None) -> None:
    response.set_cookie(
        key=name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        domain=domain,
        path="/",
    )


@router.get("/github/login")
async def github_login(config: ConfigDep) -> RedirectResponse:
    """Begin OAuth flow: issue state cookie and redirect to GitHub."""
    state = make_state_token(config)
    qs = urlencode({
        "client_id": config.github_client_id,
        "redirect_uri": config.oauth_callback_url,
        "scope": "read:user user:email",
        "state": state,
    })
    target = f"{config.github_oauth_authorize_url}?{qs}"
    response = RedirectResponse(url=target, status_code=302)
    response.set_cookie(
        key=_STATE_COOKIE,
        value=state,
        max_age=config.state_max_age_seconds,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        path="/auth",
    )
    return response


@router.get("/github/callback")
async def github_callback(
    config: ConfigDep,
    session: SessionDep,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    state_cookie: Annotated[str | None, Cookie(alias=_STATE_COOKIE)] = None,
):
    """Complete OAuth: verify state, exchange code, upsert user, set JWT cookie."""
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")

    if state_cookie is None or state_cookie != state:
        raise HTTPException(status_code=400, detail="state mismatch")

    if read_state_token(config, state) is None:
        raise HTTPException(status_code=400, detail="state expired or invalid")

    try:
        profile = await exchange_github_code(config, code)
    except GitHubOAuthError as e:
        raise HTTPException(status_code=502, detail=f"github oauth failed: {e}")

    repo = UserRepository(session)
    user = await repo.upsert_from_github(
        github_id=profile["github_id"],
        github_login=profile["github_login"],
        email=profile.get("email"),
        avatar_url=profile.get("avatar_url"),
    )
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(user)

    access_token = issue_access_token(config, user_id=user.id, github_id=user.github_id)

    # Redirect to frontend dashboard with cookie set
    response = RedirectResponse(url=f"{config.frontend_url}/dashboard", status_code=302)
    _set_access_cookie(
        response,
        name=config.cookie_name,
        token=access_token,
        max_age=config.jwt_access_ttl_seconds,
        secure=config.cookie_secure,
        domain=config.cookie_domain,
    )
    response.delete_cookie(_STATE_COOKIE, path="/auth")
    return response


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUserDep) -> UserOut:
    return UserOut.model_validate(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(config: ConfigDep, response: Response) -> Response:
    response.delete_cookie(config.cookie_name, path="/", domain=config.cookie_domain)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
