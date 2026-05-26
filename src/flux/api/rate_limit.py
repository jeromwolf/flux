"""Process-wide slowapi limiter — exported so routers can decorate handlers.

Lives in its own module to avoid a circular import between ``flux.api.app``
(which wires the limiter into the FastAPI app) and the routers (which need to
reference the same ``Limiter`` instance to register per-endpoint limits).
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _rate_key(request: Request) -> str:
    """Prefer authenticated user id so a noisy logged-in user can't DoS others
    from the same NAT egress. Falls back to the client IP for anon traffic."""
    user = getattr(request.state, "user_id", None)
    if user:
        return f"user:{user}"
    return f"ip:{get_remote_address(request)}"


# Module-level limiter so both the app factory and the routers can import it.
limiter = Limiter(key_func=_rate_key)
