"""Platform endpoints — /health, /version, /public-key.pem."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, Request, Response

from inkprint.core.db import check_db

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    db_status = await check_db()
    commit = os.environ.get("COMMIT_SHA", "dev")
    return {"status": "ok", "version": "0.1.0", "db": db_status, "commit": commit}


@router.get("/version")
async def version() -> dict[str, str]:
    """Version endpoint."""
    commit = os.environ.get("COMMIT_SHA", "dev")
    return {"version": "0.1.0", "commit_sha": commit}


@router.get("/public-key.pem")
async def public_key_pem(request: Request) -> Response:
    """Return the PEM-encoded public key."""
    pub = request.app.state.public_key
    pem = pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return Response(content=pem.decode("utf-8"), media_type="text/plain")
