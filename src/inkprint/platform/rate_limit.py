"""Per-caller fixed-window rate limiting for the write / scan endpoints.

Caps the request rate on the expensive endpoints so no caller can trigger
unbounded paid Voyage-embedding calls and outbound corpus scans. The bucket is
the caller (spec 09 §5): ``"{iss}:{sub}"`` when the platform-token middleware —
which runs before this one — authenticated the request, else the client
address, which is the visitor's leftmost ``X-Forwarded-For`` entry because the
container runs uvicorn with ``--proxy-headers --forwarded-allow-ips '*'``.

In-process (per-worker) and intentionally lightweight — a good-enough abuse
brake for a single-instance deployment, not a distributed quota system.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from inkprint.platform.platform_token import request_principal
from inkprint.platform.token_verifier import Principal

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

_Handler = Callable[[Request], Awaitable[Response]]


def rate_limit_identity(principal: Principal | None, client_host: str | None) -> str:
    """``iss:sub`` for an authenticated caller, else the client address."""
    if principal is not None:
        return f"{principal.iss}:{principal.sub}"
    return client_host or "unknown"


def install_rate_limit(app: FastAPI, *, per_minute: int, enabled: bool = True) -> None:
    """Attach the rate-limit middleware to ``app`` (no-op when disabled)."""
    if not enabled:
        return

    hits: dict[str, deque[float]] = defaultdict(deque)

    @app.middleware("http")
    async def _rate_limit_middleware(request: Request, call_next: _Handler) -> Response:
        if (request.method, request.url.path) not in _LIMITED:
            return await call_next(request)

        identity = rate_limit_identity(
            request_principal(request), request.client.host if request.client else None
        )
        key = f"{identity}|{request.url.path}"
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
        return await call_next(request)
