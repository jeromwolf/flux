"""FastAPI application factory.

Initialises the async DB engine on startup, exposes ``/healthz``, and wires
routers. Routers themselves are added incrementally as Week 3 progresses.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from flux.api import db as _db
from flux.api.schemas import HealthResponse

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build engine on startup, dispose on shutdown."""
    engine = _db.make_engine()
    _db.set_engine(engine)
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    from flux.api.routers import agents as agents_router
    from flux.api.routers import auth as auth_router
    from flux.api.routers import ws as ws_router

    app = FastAPI(
        title="Flux API",
        version=APP_VERSION,
        description="Web control plane for Flux — deploy and manage AI agents 24/7.",
        lifespan=lifespan,
    )

    @app.get("/healthz", response_model=HealthResponse, tags=["meta"])
    async def healthz() -> HealthResponse:
        """Liveness probe + DB ping."""
        db_status = "unknown"
        try:
            async with _db.get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_status = "ok"
        except Exception as e:
            db_status = f"error: {type(e).__name__}"
        return HealthResponse(status="ok", version=APP_VERSION, database=db_status)

    app.include_router(auth_router.router)
    app.include_router(agents_router.router)
    app.include_router(ws_router.router)

    return app


# Module-level instance for uvicorn: ``uvicorn flux.api.app:app``
app = create_app()
