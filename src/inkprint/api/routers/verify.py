"""Verify endpoint — POST /verify."""

from __future__ import annotations

from fastapi import APIRouter, Request

from inkprint.schemas.certificate import VerifyRequest, VerifyResponse

router = APIRouter()


@router.post("/verify", response_model=VerifyResponse)
async def verify_manifest(body: VerifyRequest, request: Request) -> VerifyResponse:
    """Verify a C2PA manifest's signature and optionally check text hash."""
    from inkprint.services.certificate_service import verify_certificate

    result = verify_certificate(
        manifest=body.manifest,
        text=body.text,
        public_key=request.app.state.public_key,
    )
    return VerifyResponse(**result)
