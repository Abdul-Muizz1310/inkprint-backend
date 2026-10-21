"""Middleware — X-Request-Id and CORS."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from starlette.middleware.cors import CORSMiddleware

_PROD_ORIGINS: Final = (
    "https://inkprint-frontend.vercel.app",
    "https://bastion-six.vercel.app",
)

# Spec 09 §6: what a browser may send. Explicit, not "*": the platform token,
# the request id and JSON bodies, plus a Bearer token and the SSE resume id.
ALLOWED_REQUEST_HEADERS: Final = (
    "content-type",
    "x-platform-token",
    "x-request-id",
    "authorization",
    "last-event-id",
)


def _allowed_origins(app_env: str) -> list[str]:
    origins = list(_PROD_ORIGINS)
    if app_env != "production":
        origins.append("http://localhost:3000")
    return origins


def add_request_id(app: FastAPI) -> None:
    """Echo ``X-Request-Id`` (or a fresh UUID) on every response."""

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        response: Response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


def add_cors(app: FastAPI, *, app_env: str) -> None:
    """Attach CORS. Call it last: the last middleware added is the outermost, and
    CORS must be outermost so it answers preflights itself and decorates a 401/503
    from the platform-token middleware (spec 09 §6, spec 10).
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(app_env),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=list(ALLOWED_REQUEST_HEADERS),
        expose_headers=["x-request-id"],
    )
