"""SQLAlchemy 2.x async engine + session factory.

Driver is chosen from the URL scheme:
    postgresql+asyncpg://...   -> production (docker-compose)
    sqlite+aiosqlite://...     -> tests / quick local

Environment:
    FLUX_DATABASE_URL  (overrides default)
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


DEFAULT_DATABASE_URL = "postgresql+asyncpg://flux:flux_dev@localhost:5432/flux"


def get_database_url() -> str:
    """Read the configured database URL (env > default)."""
    return os.environ.get("FLUX_DATABASE_URL", DEFAULT_DATABASE_URL)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def make_engine(url: str | None = None, *, echo: bool = False) -> AsyncEngine:
    """Build an AsyncEngine. Callers manage lifecycle (dispose on shutdown)."""
    return create_async_engine(url or get_database_url(), echo=echo, future=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# --- App-wide singletons (initialised in app.py via lifespan) ---------------

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def set_engine(engine: AsyncEngine) -> None:
    """Install the process-wide engine + sessionmaker."""
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = make_sessionmaker(engine)


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("DB engine not initialised. Call set_engine() first.")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("DB engine not initialised. Call set_engine() first.")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a session per request."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
