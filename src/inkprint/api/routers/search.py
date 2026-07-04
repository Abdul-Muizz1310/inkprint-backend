"""Search endpoint — GET /search."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from inkprint.schemas.certificate import SearchResponse

router = APIRouter()

SearchMode = Literal["exact", "semantic"]


@router.get("/search", response_model=SearchResponse)
async def search_certificates(
    text: Annotated[str, Query(description="Text to search for")],
    mode: Annotated[
        SearchMode, Query(description="Search mode: 'exact' or 'semantic'")
    ] = "semantic",
) -> SearchResponse:
    """Search for certificates by text content.

    ``mode`` is a closed set: an unknown value is rejected with 422 at the HTTP
    boundary rather than silently returning empty results.
    """
    from inkprint.services.certificate_service import search_certificates as svc_search

    result = await svc_search(text=text, mode=mode)
    return SearchResponse(**result)
