"""Search endpoint — GET /search."""

from __future__ import annotations

from fastapi import APIRouter, Query

from inkprint.schemas.certificate import SearchResponse

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search_certificates(
    text: str = Query(..., description="Text to search for"),
    mode: str = Query("semantic", description="Search mode: 'exact' or 'semantic'"),
) -> SearchResponse:
    """Search for certificates by text content."""
    from inkprint.services.certificate_service import search_certificates as svc_search

    result = svc_search(text=text, mode=mode)
    return SearchResponse(**result)
