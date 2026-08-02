#!/usr/bin/env python
"""Post-deploy smoke check: poll the live ``/health`` endpoint.

Deliberately *skippable*. The Render deployment is on the free tier and is
periodically cold or suspended, so an unconditional live probe in CI would turn
unrelated pull requests red. When ``SMOKE_BASE_URL`` is unset or blank the
check prints a notice, makes *zero* HTTP requests, and exits 0; it only fails
when a base URL was supplied and the service did not report healthy within the
retry budget.

``SMOKE_BASE_URL`` is a bare origin with no path and no trailing slash — this
script appends ``/health`` itself via :func:`health_url`, so the variable stays
reusable for any other path a future probe wants.

"Healthy" means more than HTTP 200: the body must be JSON with ``status == "ok"``
*and* ``db == "ok"``. A deploy that boots without its database is not a good
deploy, and that exact state (``db: down``) is what this repo shipped before.

Usage::

    SMOKE_BASE_URL=https://inkprint-backend.onrender.com \\
        uv run python scripts/smoke_health.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx

SMOKE_URL_ENV = "SMOKE_BASE_URL"
HEALTH_PATH = "/health"
DEFAULT_ATTEMPTS = 10
DEFAULT_DELAY_SECONDS = 15.0
REQUEST_TIMEOUT_SECONDS = 20.0


def health_url(base_url: str) -> str:
    """Join ``base_url`` with ``/health`` using exactly one separator.

    The repository variable holds a bare origin, but a hand-set value may still
    arrive with a trailing slash; collapsing it here keeps the probed URL free
    of the ``//health`` that a naive concatenation would produce.
    """
    return f"{base_url.strip().rstrip('/')}{HEALTH_PATH}"


def _describe(response: httpx.Response) -> str:
    body = response.text.strip().replace("\n", " ")
    return f"HTTP {response.status_code} {body[:200]}"


def _is_healthy(response: httpx.Response) -> tuple[bool, str]:
    """Return (healthy, reason)."""
    if response.status_code != 200:
        return False, _describe(response)
    try:
        payload: Any = response.json()
    except ValueError:
        return False, f"non-JSON body: {_describe(response)}"
    if not isinstance(payload, dict):
        return False, f"unexpected JSON shape: {payload!r}"
    if payload.get("status") != "ok":
        return False, f"status={payload.get('status')!r}"
    if payload.get("db") != "ok":
        return False, f"db={payload.get('db')!r}"
    return True, f"status=ok db=ok commit_sha={payload.get('commit_sha')!r}"


def main(
    base_url: str | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> int:
    """Poll ``base_url`` + ``/health`` until healthy. Returns an exit code."""
    if base_url is None:
        base_url = os.environ.get(SMOKE_URL_ENV)
    if base_url is None or not base_url.strip():
        print(
            f"[smoke] {SMOKE_URL_ENV} is not set - skipping the live /health poll. "
            "Set it as a repository variable (a bare origin, no /health) to "
            "enable the post-deploy check."
        )
        return 0

    url = health_url(base_url)
    last_reason = "no attempt made"
    with httpx.Client(transport=transport, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
            else:
                healthy, reason = _is_healthy(response)
                last_reason = reason
                if healthy:
                    print(f"[smoke] {url} healthy on attempt {attempt}/{attempts} ({reason})")
                    return 0
            print(f"[smoke] attempt {attempt}/{attempts} not healthy yet: {last_reason}")
            if attempt < attempts and delay:
                time.sleep(delay)

    print(f"[smoke] FAILED after {attempts} attempt(s): {last_reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
