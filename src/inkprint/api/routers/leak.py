"""Leak scan endpoints — POST /leak-scan, GET /leak-scan/{id}, GET /leak-scan/{id}/stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from inkprint.schemas.certificate import LeakScanRequest, LeakScanResponse
from inkprint.services import certificate_service, leak_service

router = APIRouter()


@router.post("/leak-scan", status_code=202, response_model=LeakScanResponse)
async def create_leak_scan(body: LeakScanRequest) -> LeakScanResponse:
    """Start a new leak scan for a certificate."""
    # Verify the certificate exists
    cert = certificate_service.get_certificate(str(body.certificate_id))
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    record = leak_service.create_scan(
        certificate_id=body.certificate_id,
        corpora=body.corpora,
    )
    return LeakScanResponse(scan_id=UUID(record["scan_id"]), status=record["status"])


@router.get("/leak-scan/{scan_id}")
async def get_leak_scan(scan_id: UUID) -> dict[str, Any]:
    """Get the status / result of a leak scan."""
    record = leak_service.get_scan(str(scan_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return record


@router.get("/leak-scan/{scan_id}/stream")
async def stream_leak_scan(scan_id: UUID) -> StreamingResponse:
    """Stream scan events via SSE."""
    record = leak_service.get_scan(str(scan_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    async def event_generator() -> AsyncIterator[str]:
        yield f"data: {{'scan_id': '{scan_id}', 'status': '{record['status']}'}}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
