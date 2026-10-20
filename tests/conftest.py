"""Shared test fixtures.

Every test runs against an isolated, in-memory SQLite database — no files, no
Postgres, no Docker. ``db_tables`` (autouse) binds a fresh ``StaticPool``
engine (so every session, including background tasks, sees the same database),
creates the schema from the ORM metadata, and disposes it afterward.
"""

from __future__ import annotations

import os

# Disable the per-IP rate limiter for the test suite: many tests hammer the same
# endpoints from a single (test) client IP and would otherwise trip the throttle.
# The limiter has its own dedicated unit test (test_rate_limit.py). Set before
# any app import so create_app reads it.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# Hermetic: never archive to a real R2 bucket, even when a developer's .env
# holds credentials. Tests that need R2 patch the settings and the client
# themselves (spec 08). Assigned, not defaulted, so a shell export cannot leak in.
os.environ["R2_ENDPOINT"] = ""
os.environ["R2_ACCESS_KEY_ID"] = ""
os.environ["R2_SECRET_ACCESS_KEY"] = ""
# The test settings (spec 09 §3): with no trusted key configured, protected
# routes proceed instead of failing closed, so app-level tests need no token.
# Blank every key source so neither a developer's .env nor the in-code default
# bastion URL makes the app fetch a real key; the contract-v2 tests build their
# own app with explicit keys (tests/unit/test_platform_token.py).
os.environ["APP_ENV"] = "test"
# Hermetic database too: importing inkprint.main builds the module-level app,
# whose engine and slowquery store (spec 10) come from DATABASE_URL. Blank, it is
# the local SQLite default and the in-memory store, never a developer's Neon
# branch. Tests that need Postgres build their own engine (the postgres tier).
os.environ["DATABASE_URL"] = ""
os.environ["DEMO_MODE"] = "false"
os.environ["BASTION_SIGNING_KEY_PUBLIC"] = ""
os.environ["BASTION_PUBLIC_KEY_URL"] = ""
os.environ["INKPRINT_FRONTEND_SIGNING_KEY_PUBLIC"] = ""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from inkprint.core import db, storage_health


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
    storage_health.reset()
    try:
        yield
    finally:
        await db.dispose_engine()
        storage_health.reset()
