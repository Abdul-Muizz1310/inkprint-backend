"""Per-IP fixed-window rate limiting for the write / scan endpoints.

There is otherwise no throttle anywhere in the app, and ``DEMO_MODE`` defaults
to true (platform-token auth bypassed), so any client could trigger unbounded
paid Voyage-embedding calls and outbound corpus scans. This middleware caps the
request rate per client IP on the expensive endpoints.

In-process (per-worker) and intentionally lightweight — a good-enough abuse
brake for a single-instance demo deployment, not a distributed quota system.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

# (method, path) pairs that are rate limited.
_LIMITED: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/certificates"),
        ("POST", "/certificates/batch"),
        ("POST", "/verify"),
        ("POST", "/verify/batch"),
        ("POST", "/leak-scan"),
    }
)

_WINDOW_SECONDS = 60.0


def install_rate_limit(app: FastAPI, *, per_minute: int, enabled: bool = True) -> None:
    """Attach the per-IP rate-limit middleware to ``app`` (no-op when disabled)."""
    if not enabled:
        return

    hits: dict[str, deque[float]] = defaultdict(deque)

    @app.middleware("http")
    async def _rate_limit_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if (request.method, request.url.path) not in _LIMITED:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}|{request.url.path}"
        now = time.monotonic()
        bucket = hits[key]
        while bucket and now - bucket[0] > _WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= per_minute:
            retry_after = max(1, int(_WINDOW_SECONDS - (now - bucket[0])))
            return JSONResponse(
                {"error": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)
        response: Response = await call_next(request)
        return response
