"""Shared test fixtures.

Persistence is isolated per test and kept entirely in memory — no files, no
Postgres, no Docker. ``_db_env`` (autouse, sync) resets the cached engine and
points the lazy default at an in-memory SQLite URL, so even tests that only
probe ``/health`` connect cleanly. ``db_tables`` (async) binds a shared
in-memory engine (``StaticPool`` so every session sees the same database) and
creates the schema, for tests that actually read/write rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from inkprint.core import db
from inkprint.core.config import get_settings


@pytest.fixture(autouse=True)
def _db_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset the cached engine and use an in-memory SQLite default per test."""
    db._engine = None
    db._session_factory = None
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    get_settings.cache_clear()
    yield
    db._engine = None
    db._session_factory = None
    get_settings.cache_clear()


@pytest.fixture()
async def db_tables() -> AsyncIterator[None]:
    """Bind a shared in-memory SQLite database and create all ORM tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(engine)
    await db.init_models()
    try:
        yield
    finally:
        await db.dispose_engine()
