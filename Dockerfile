FROM python:3.12-slim AS base

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies (no dev deps in production)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
RUN chmod +x ./docker-entrypoint.sh

# Install the project itself
RUN uv sync --frozen --no-dev

# Bake the commit SHA into the image when the builder passes it. Left EMPTY (not
# "unknown") on purpose: a placeholder here would be reported by /health and
# /version as though it were a real commit, whereas an empty value lets
# platform.health.resolve_commit_sha() fall through to Render's injected
# RENDER_GIT_COMMIT. Render Blueprints cannot pass Docker build args, so that
# runtime variable is the mechanism that actually works there.
ARG COMMIT_SHA=""
ENV COMMIT_SHA=${COMMIT_SHA}

EXPOSE 8000
# The entrypoint applies Alembic migrations before handing off to the CMD.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uv", "run", "--no-dev", "uvicorn", "inkprint.main:app", "--host", "0.0.0.0", "--port", "8000"]
