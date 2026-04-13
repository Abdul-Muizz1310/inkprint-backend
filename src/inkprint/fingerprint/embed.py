"""Voyage AI embedding computation."""

from __future__ import annotations

import voyageai


async def compute_embedding(text: str) -> list[float]:
    """Compute an embedding using Voyage AI.

    Uses the configured model (default: voyage-3-lite).
    """
    from inkprint.core.config import get_settings

    settings = get_settings()
    client = voyageai.AsyncClient()  # type: ignore[attr-defined]
    result = await client.embed([text], model=settings.voyage_model)
    return list(result.embeddings[0])
