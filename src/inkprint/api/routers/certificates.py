"""Certificate CRUD + manifest, QR, download endpoints."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from uuid import UUID

import qrcode
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, HTTPException, Request, Response

from inkprint.schemas.certificate import CertificateCreate, CertificateResponse

router = APIRouter()


def _get_keys(request: Request) -> tuple[Any, Any, str]:
    return request.app.state.private_key, request.app.state.public_key, request.app.state.key_id


def _public_key_pem(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)


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

    record = await svc_get(str(cert_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return CertificateResponse(**{k: record[k] for k in CertificateResponse.model_fields})


@router.get("/certificates/{cert_id}/manifest")
async def get_manifest(cert_id: UUID) -> dict[str, Any]:
    """Retrieve the C2PA manifest for a certificate."""
    from inkprint.services.certificate_service import get_certificate as svc_get

    record = await svc_get(str(cert_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    manifest: dict[str, Any] = record["manifest"]
    return manifest


@router.get("/certificates/{cert_id}/qr")
async def get_qr(cert_id: UUID, request: Request) -> Response:
    """Generate a QR code PNG linking to the certificate's verify page."""
    from inkprint.services.certificate_service import get_certificate as svc_get

    record = await svc_get(str(cert_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    base = request.app.state.settings.frontend_base_url.rstrip("/")
    url = f"{base}/verify/{cert_id}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/certificates/{cert_id}/download")
async def download_certificate(cert_id: UUID, request: Request) -> Response:
    """Download a ``.zip`` archive of the certificate.

    The archive contains ``manifest.json`` (the C2PA manifest), ``public_key.pem``
    (the Ed25519 verification key), and ``content.txt`` (the original text) — so
    a recipient has everything needed to verify provenance offline.
    """
    from inkprint.services.certificate_service import get_certificate as svc_get

    record = await svc_get(str(cert_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    _, public_key, _ = _get_keys(request)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(record["manifest"], indent=2))
        zf.writestr("public_key.pem", _public_key_pem(public_key))
        zf.writestr("content.txt", record["text"])
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{cert_id}.zip"'},
    )
