"""Voyage AI embedding computation."""

from __future__ import annotations

import voyageai


async def compute_embedding(text: str) -> list[float]:
    """Compute a 768-dimensional embedding using Voyage AI.

    Uses the configured model (default: voyage-3-lite).
    """
    client = voyageai.AsyncClient()
    result = await client.embed([text], model="voyage-3-lite")
    return list(result.embeddings[0])
