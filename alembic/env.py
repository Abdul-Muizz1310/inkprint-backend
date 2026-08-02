"""Alembic environment configuration.

Migrations run over the **async** driver the application already ships
(``asyncpg`` for Postgres, ``aiosqlite`` for SQLite). The previous version
stripped ``+asyncpg`` from ``DATABASE_URL`` to get a "sync driver", which makes
SQLAlchemy fall back to ``psycopg2`` — a package this project does not depend on
and which is absent from the production image. ``alembic upgrade head`` therefore
could not run anywhere the app actually runs; it only worked on a machine that
happened to have psycopg2 installed for other reasons.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Async drivers keyed by the scheme prefix they replace. Longest-prefix first so
# an already-async URL is left alone.
_ASYNC_DRIVERS = {
    "postgresql+asyncpg://": "postgresql+asyncpg://",
    "postgresql+psycopg2://": "postgresql+asyncpg://",
    "postgresql+psycopg://": "postgresql+asyncpg://",
    "postgresql://": "postgresql+asyncpg://",
    "postgres://": "postgresql+asyncpg://",
    "sqlite+aiosqlite://": "sqlite+aiosqlite://",
    "sqlite://": "sqlite+aiosqlite://",
}


def to_async_url(url: str) -> str:
    """Return ``url`` with an async driver, or unchanged when none is known."""
    for prefix in sorted(_ASYNC_DRIVERS, key=len, reverse=True):
        if url.startswith(prefix):
            return _ASYNC_DRIVERS[prefix] + url[len(prefix) :]
    return url


database_url = os.environ.get("DATABASE_URL", "")
if database_url:
    config.set_main_option("sqlalchemy.url", to_async_url(database_url))

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    connectable = create_async_engine(
        config.get_main_option("sqlalchemy.url", ""),
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode over the async driver."""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
