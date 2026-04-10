"""Certificate CRUD + manifest, QR, download endpoints."""

from __future__ import annotations

import io
from uuid import UUID

import qrcode
from fastapi import APIRouter, HTTPException, Request, Response

from inkprint.schemas.certificate import CertificateCreate, CertificateResponse

router = APIRouter()


def _get_keys(request: Request) -> tuple:
    return request.app.state.private_key, request.app.state.public_key, request.app.state.key_id


@router.post("/certificates", status_code=201, response_model=CertificateResponse)
async def create_certificate(body: CertificateCreate, request: Request) -> CertificateResponse:
    """Create a new content certificate."""
    from inkprint.services.certificate_service import create_certificate as svc_create

    text_bytes = body.text.encode("utf-8")
    if len(text_bytes) > request.app.state.settings.max_text_bytes:
        raise HTTPException(status_code=413, detail="Text exceeds maximum allowed size")

    private_key, public_key, key_id = _get_keys(request)
    record = await svc_create(
        text=body.text,
        author=body.author,
        metadata=body.metadata,
        private_key=private_key,
        public_key=public_key,
        key_id=key_id,
    )
    return CertificateResponse(**{k: record[k] for k in CertificateResponse.model_fields})


@router.get("/certificates/{cert_id}", response_model=CertificateResponse)
async def get_certificate(cert_id: UUID) -> CertificateResponse:
    """Retrieve a certificate by ID."""
    from inkprint.services.certificate_service import get_certificate as svc_get

    record = svc_get(str(cert_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return CertificateResponse(**{k: record[k] for k in CertificateResponse.model_fields})


@router.get("/certificates/{cert_id}/manifest")
async def get_manifest(cert_id: UUID) -> dict:
    """Retrieve the C2PA manifest for a certificate."""
    from inkprint.services.certificate_service import get_certificate as svc_get

    record = svc_get(str(cert_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return record["manifest"]


@router.get("/certificates/{cert_id}/qr")
async def get_qr(cert_id: UUID) -> Response:
    """Generate a QR code PNG for the certificate."""
    from inkprint.services.certificate_service import get_certificate as svc_get

    record = svc_get(str(cert_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    url = f"https://inkprint.dev/verify/{cert_id}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/certificates/{cert_id}/download")
async def download_certificate(cert_id: UUID) -> Response:
    """Download the original text of a certificate."""
    from inkprint.services.certificate_service import get_certificate as svc_get

    record = svc_get(str(cert_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return Response(
        content=record["text"],
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{cert_id}.txt"'},
    )
