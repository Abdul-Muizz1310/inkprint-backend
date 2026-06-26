"""Shared test fixtures.

Every test runs against an isolated, in-memory SQLite database — no files, no
Postgres, no Docker. ``db_tables`` (autouse) binds a fresh ``StaticPool``
engine (so every session, including background tasks, sees the same database),
creates the schema from the ORM metadata, and disposes it afterward.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from inkprint.core import db


@pytest.fixture(autouse=True)
async def db_tables() -> AsyncIterator[None]:
    """Bind a fresh in-memory SQLite database with the full schema per test."""
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
