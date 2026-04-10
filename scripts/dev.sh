#!/usr/bin/env bash
set -euo pipefail

# Start the development server with auto-reload
uv run uvicorn inkprint.main:app --reload --host 0.0.0.0 --port "${PORT:-8000}"
