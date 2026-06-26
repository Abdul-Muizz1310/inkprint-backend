"""Async SQLAlchemy engine, session factory, and lifecycle helpers.

When ``DATABASE_URL`` is unset the backend falls back to a local SQLite file
(``sqlite+aiosqlite``) so it boots and persists out of the box without a
Postgres instance. Production sets ``DATABASE_URL`` to a Neon/Postgres DSN.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from inkprint.core.config import get_settings

# Local-first default: a SQLite file in the working directory. Requires no
# external service, so the app works offline and in tests.
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./inkprint.db"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _resolve_database_url() -> str:
    """Return the configured DSN, or the local SQLite fallback."""
    return get_settings().database_url or DEFAULT_DATABASE_URL


def get_engine() -> AsyncEngine:
    """Get or create the process-wide async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(_resolve_database_url(), echo=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory bound to the engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@contextlib.asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield a session, committing on success and rolling back on error."""
    session = get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_models() -> None:
    """Create all tables from the ORM metadata (idempotent)."""
    from inkprint.models import Base

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def configure_engine(engine: AsyncEngine) -> None:
    """Bind the global engine + session factory to ``engine``.

    Used by the test harness to point persistence at an isolated SQLite
    database. Replaces any existing engine without disposing it (the caller
    owns the lifecycle of the engine it passes in).
    """
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def dispose_engine() -> None:
    """Dispose the engine and clear the cached factory (mainly for tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def check_db() -> str:
    """Probe database connectivity. Returns 'ok' or 'down'."""
    from sqlalchemy import text

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "down"
