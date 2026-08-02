#!/bin/sh
# Container entrypoint: bring the schema to head, then start the server.
#
# Render's free instance type does not support pre-deploy commands (they require
# a paid instance), so a Blueprint `preDeployCommand` would silently never run.
# The container itself is therefore the only place a migration step can execute
# on every deploy. `alembic upgrade head` is idempotent: on a database already
# at head it is a no-op.
#
# `--no-dev` matches the image build (`uv sync --frozen --no-dev`); without it
# `uv run` re-syncs dev dependencies at container start, slowing every cold boot.
#
# A migration failure aborts startup on purpose - serving traffic against an
# un-migrated schema is worse than failing the deploy loudly.
#
# SQLite has no migration chain here (the migrations are Postgres-targeted, and
# 0001 opens with CREATE EXTENSION vector), so it is skipped; the application
# lifespan creates the SQLite schema from the ORM metadata instead.
set -e

case "${DATABASE_URL:-}" in
  postgres://* | postgresql://* | postgresql+*://*)
    echo "[entrypoint] applying Alembic migrations (alembic upgrade head)"
    uv run --no-dev alembic upgrade head
    echo "[entrypoint] migrations applied"
    ;;
  *)
    echo "[entrypoint] DATABASE_URL is not Postgres - skipping Alembic; the SQLite schema is auto-created at startup"
    ;;
esac

exec "$@"
