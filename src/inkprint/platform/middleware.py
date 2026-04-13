"""Middleware — X-Request-Id and CORS."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from starlette.middleware.cors import CORSMiddleware

_PROD_ORIGINS = [
    "https://inkprint-frontend.vercel.app",
    "https://bastion.vercel.app",
]


def _get_allowed_origins() -> list[str]:
    origins = list(_PROD_ORIGINS)
    if os.environ.get("APP_ENV", "development") != "production":
        origins.append("http://localhost:3000")
    return origins


def add_middleware(app: FastAPI) -> None:
    """Attach all middleware to the FastAPI app."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        response: Response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
