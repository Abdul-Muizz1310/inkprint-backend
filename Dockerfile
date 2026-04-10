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

# Install the project itself
RUN uv sync --frozen --no-dev

# Bake commit SHA into the image
ARG COMMIT_SHA=unknown
ENV COMMIT_SHA=${COMMIT_SHA}

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "inkprint.main:app", "--host", "0.0.0.0", "--port", "8000"]
