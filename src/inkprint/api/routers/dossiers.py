"""Dossier envelope endpoint — POST /dossiers/envelope."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from inkprint.schemas.envelope import EnvelopeRequest, EnvelopeResponse
from inkprint.services.envelope_service import (
    EnvelopeConflictError,
    UnknownCertificateError,
    create_envelope,
)

router = APIRouter()


def _get_signing(request: Request) -> tuple[Any, str]:
    return request.app.state.private_key, request.app.state.key_id


@router.post("/dossiers/envelope", status_code=200, response_model=EnvelopeResponse)
async def create_dossier_envelope(
    body: EnvelopeRequest, request: Request
) -> EnvelopeResponse:
    """Build, sign, and persist a dossier envelope manifest."""
    private_key, key_id = _get_signing(request)

    try:
        record = create_envelope(
            dossier_id=body.dossier_id,
            evidence_cert_ids=list(body.evidence_cert_ids),
            debate_transcript_hash=body.debate_transcript_hash,
            perf_receipt_hash=body.perf_receipt_hash,
            metadata=body.metadata,
            private_key=private_key,
            key_id=key_id,
        )
    except UnknownCertificateError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown certificate: {exc.certificate_id}",
        ) from exc
    except EnvelopeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return EnvelopeResponse(
        envelope_id=record["envelope_id"],
        envelope_manifest=record["envelope_manifest"],
        envelope_signature=record["envelope_signature"],
        created_at=record["created_at"],
    )
