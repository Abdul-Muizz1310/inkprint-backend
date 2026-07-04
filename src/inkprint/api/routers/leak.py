"""Leak scan endpoints — POST /leak-scan, GET /leak-scan/{id}, GET /leak-scan/{id}/stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from inkprint.schemas.certificate import LeakScanRequest, LeakScanResponse
from inkprint.services import certificate_service, leak_service

# Terminal job states — the stream closes once one is reached.
_TERMINAL = {"complete", "error"}
# How long to wait for the next progress event before re-polling the DB.
_STREAM_POLL_TIMEOUT = 15.0

router = APIRouter()


@router.post("/leak-scan", status_code=202, response_model=LeakScanResponse)
async def create_leak_scan(
    body: LeakScanRequest, background_tasks: BackgroundTasks
) -> LeakScanResponse:
    """Start a new leak scan for a certificate.

    Returns 202 immediately with a ``pending`` job; the scan runs as a
    background task that persists results and advances the job to ``complete``.
    """
    cert = await certificate_service.get_certificate(str(body.certificate_id))
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    record = await leak_service.create_scan(
        certificate_id=body.certificate_id,
        corpora=body.corpora,
    )
    background_tasks.add_task(
        leak_service.run_scan,
        UUID(record["scan_id"]),
        body.certificate_id,
        record["corpora"],
    )
    return LeakScanResponse(scan_id=UUID(record["scan_id"]), status=record["status"])


@router.get("/leak-scan/{scan_id}")
async def get_leak_scan(scan_id: UUID) -> dict[str, Any]:
    """Get the status / result of a leak scan."""
    record = await leak_service.get_scan(str(scan_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return record


@router.get("/leak-scan/{scan_id}/stream")
async def stream_leak_scan(scan_id: UUID) -> StreamingResponse:
    """Stream live leak-scan progress via SSE.

    Emits an initial snapshot, then one ``corpus_complete`` event per corpus as
    the background scan finishes it, and a final ``complete``/``error`` event —
    consuming the progress channel published by :func:`leak_service.run_scan`.
    An already-finished scan emits its snapshot once and closes.
    """
    record = await leak_service.get_scan(str(scan_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    sid = str(scan_id)

    def _snapshot(rec: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "status",
            "scan_id": sid,
            "status": rec["status"],
            "hit_count": rec["hit_count"],
            "results": rec["results"],
        }

    async def event_generator() -> AsyncIterator[str]:
        # Subscribe *before* re-checking status so no event fired between the
        # initial read and subscription is lost.
        async with leak_service.progress_subscription(sid) as queue:
            current = await leak_service.get_scan(sid)
            if current is None:
                return
            yield f"data: {json.dumps(_snapshot(current))}\n\n"
            if current["status"] in _TERMINAL:
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_STREAM_POLL_TIMEOUT)
                except TimeoutError:
                    # Fallback: re-poll the DB so a client still terminates even
                    # if the publishing worker died (reaper will finish the job).
                    latest = await leak_service.get_scan(sid)
                    if latest is None:
                        return
                    yield f"data: {json.dumps(_snapshot(latest))}\n\n"
                    if latest["status"] in _TERMINAL:
                        return
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("complete", "error"):
                    return

    return StreamingResponse(event_generator(), media_type="text/event-stream")
