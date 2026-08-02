"""Platform endpoints — /health, /version, /public-key.pem."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, Request, Response

from inkprint.core.db import check_db

router = APIRouter()

# Values that mean "no build provenance available", not a commit. ``unknown`` is
# the Dockerfile's ARG default, so reporting it verbatim looked like a real answer.
_PLACEHOLDER_SHAS = frozenset({"", "unknown", "none", "dev", "null"})


def resolve_commit_sha() -> str:
    """Return the deployed commit, or ``"dev"`` when genuinely unknown.

    Order: an explicit ``COMMIT_SHA`` (baked at image build), then Render's
    injected ``RENDER_GIT_COMMIT`` (available on every Render service at runtime,
    and the only mechanism that works from a Blueprint, which cannot pass Docker
    build args). Placeholder values are skipped rather than reported.
    """
    for key in ("COMMIT_SHA", "RENDER_GIT_COMMIT"):
        value = os.environ.get(key, "").strip()
        if value and value.lower() not in _PLACEHOLDER_SHAS:
            return value
    return "dev"


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    db_status = await check_db()
    return {
        "status": "ok",
        "version": "0.1.0",
        "db": db_status,
        "commit_sha": resolve_commit_sha(),
    }


@router.get("/version")
async def version() -> dict[str, str]:
    """Version endpoint."""
    return {"version": "0.1.0", "commit_sha": resolve_commit_sha()}


@router.get("/public-key.pem")
async def public_key_pem(request: Request) -> Response:
    """Return the PEM-encoded public key."""
    pub = request.app.state.public_key
    pem = pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return Response(content=pem.decode("utf-8"), media_type="text/plain")
