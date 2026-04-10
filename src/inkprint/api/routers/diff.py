"""Diff endpoint — POST /diff."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from inkprint.schemas.certificate import DiffRequest, DiffResponse

router = APIRouter()


@router.post("/diff", response_model=DiffResponse)
async def diff_text(body: DiffRequest) -> DiffResponse:
    """Compare new text against a parent certificate's fingerprints."""
    from inkprint.services.certificate_service import diff_certificate

    result = await diff_certificate(parent_id=str(body.parent_id), text=body.text)
    if result is None:
        raise HTTPException(status_code=404, detail="Parent certificate not found")
    return DiffResponse(**result)
