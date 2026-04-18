"""Batch endpoints — POST /certificates/batch, POST /verify/batch."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from inkprint.schemas.batch import (
    BatchCertificateCreateRequest,
    BatchCertificateRecord,
    BatchCertificateResponse,
    BatchFingerprints,
    BatchVerifyItemResult,
    BatchVerifyRequest,
    BatchVerifyResponse,
)
from inkprint.services.batch_service import (
    EmbeddingServiceUnavailableError,
    create_batch,
    verify_batch,
)

router = APIRouter()


def _get_keys(request: Request) -> tuple[Any, Any, str]:
    return (
        request.app.state.private_key,
        request.app.state.public_key,
        request.app.state.key_id,
    )


@router.post(
    "/certificates/batch",
    status_code=200,
    response_model=BatchCertificateResponse,
)
async def create_certificates_batch(
    body: BatchCertificateCreateRequest, request: Request
) -> BatchCertificateResponse:
    """Issue N certificates atomically."""
    private_key, public_key, key_id = _get_keys(request)

    items_as_dicts: list[dict[str, Any]] = [
        {"text": it.text, "author": it.author, "metadata": it.metadata}
        for it in body.items
    ]

    try:
        service_results = await create_batch(
            items_as_dicts,
            private_key=private_key,
            public_key=public_key,
            key_id=key_id,
        )
    except EmbeddingServiceUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Embedding service unavailable"
        ) from exc

    return BatchCertificateResponse(
        certificates=[
            BatchCertificateRecord(
                certificate_id=r["certificate_id"],
                manifest=r["manifest"],
                fingerprints=BatchFingerprints(**r["fingerprints"]),
            )
            for r in service_results
        ]
    )


@router.post("/verify/batch", status_code=200, response_model=BatchVerifyResponse)
async def verify_certificates_batch(
    body: BatchVerifyRequest, request: Request
) -> BatchVerifyResponse:
    """Batch signature + fingerprint verification."""
    _, public_key, _ = _get_keys(request)

    items_as_dicts: list[dict[str, Any]] = [
        {"certificate_id": it.certificate_id, "text": it.text} for it in body.items
    ]
    service_results = await verify_batch(items_as_dicts, public_key=public_key)
    return BatchVerifyResponse(
        results=[BatchVerifyItemResult(**r) for r in service_results]
    )
