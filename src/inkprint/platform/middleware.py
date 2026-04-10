"""Middleware — X-Request-Id and CORS."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from starlette.middleware.cors import CORSMiddleware

ALLOWED_ORIGINS = [
    "https://inkprint-frontend.vercel.app",
    "https://bastion.vercel.app",
    "http://localhost:3000",
]


def add_middleware(app: FastAPI) -> None:
    """Attach all middleware to the FastAPI app."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
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
