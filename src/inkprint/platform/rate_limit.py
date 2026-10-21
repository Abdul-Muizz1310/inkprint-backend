"""Per-caller fixed-window rate limiting for the write / scan endpoints.

Caps the request rate on the expensive endpoints so no caller can trigger
unbounded paid Voyage-embedding calls and outbound corpus scans. The bucket is
the caller (spec 09 §5), as the platform-token middleware — which runs before
this one — identified it:

- bastion's key: ``"bastion:{sub}"``, the visitor pseudonym;
- the frontend's key: ``"{iss}:{address}"`` — its ``sub`` is constant, so keying
  on it would put every visitor of the site in one bucket;
- no token: the bare address.

The address is ``request.client.host``, the visitor's leftmost
``X-Forwarded-For`` entry because the container runs uvicorn with
``--proxy-headers --forwarded-allow-ips '*'``; the frontend's proxy sets exactly
one address there.

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
from inkprint.platform.token_verifier import BASTION_ISSUER, Principal

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
    """The bucket: ``bastion:{sub}``, ``{frontend iss}:{address}``, or the bare address."""
    address = client_host or "unknown"
    if principal is None:
        return address
    if principal.iss == BASTION_ISSUER:
        return f"{BASTION_ISSUER}:{principal.sub}"
    return f"{principal.iss}:{address}"


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
