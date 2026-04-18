"""FastAPI application assembly."""

from __future__ import annotations

import base64
import os
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi import FastAPI

from inkprint.api.routers.batch import router as batch_router
from inkprint.api.routers.certificates import router as certificates_router
from inkprint.api.routers.diff import router as diff_router
from inkprint.api.routers.dossiers import router as dossiers_router
from inkprint.api.routers.leak import router as leak_router
from inkprint.api.routers.search import router as search_router
from inkprint.api.routers.verify import router as verify_router
from inkprint.core.config import Settings
from inkprint.platform.health import router as health_router
from inkprint.platform.middleware import add_middleware


def _load_keys() -> tuple[Any, Any, str]:
    """Load or generate signing keys."""
    priv_b64 = os.environ.get("INKPRINT_SIGNING_KEY_PRIVATE", "")
    pub_b64 = os.environ.get("INKPRINT_SIGNING_KEY_PUBLIC", "")
    key_id = os.environ.get("INKPRINT_KEY_ID", "inkprint-ed25519-dev")

    if priv_b64 and pub_b64:
        from inkprint.core.keys import load_signing_keys

        return load_signing_keys()

    # Generate ephemeral keys for development / testing
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Set env vars so other modules can pick them up
    priv_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    pub_pem = public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    os.environ["INKPRINT_SIGNING_KEY_PRIVATE"] = base64.b64encode(priv_pem).decode()
    os.environ["INKPRINT_SIGNING_KEY_PUBLIC"] = base64.b64encode(pub_pem).decode()
    os.environ["INKPRINT_KEY_ID"] = key_id

    return private_key, public_key, key_id


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = Settings()

    application = FastAPI(
        title="inkprint",
        version="0.1.0",
        description="Content provenance and AI-training-data leak detection",
    )

    # Load signing keys
    private_key, public_key, key_id = _load_keys()
    application.state.private_key = private_key
    application.state.public_key = public_key
    application.state.key_id = key_id
    application.state.settings = settings

    # Middleware (must be added before routers for CORS to work on all routes)
    add_middleware(application)

    # Routers
    application.include_router(health_router)
    application.include_router(certificates_router)
    application.include_router(batch_router)
    application.include_router(dossiers_router)
    application.include_router(verify_router)
    application.include_router(diff_router)
    application.include_router(leak_router)
    application.include_router(search_router)

    return application


app = create_app()
