"""Voyage AI embedding computation.

The Voyage async client is constructed once per process (``_client``) and reused
across calls so we keep the underlying TLS/connection pool warm instead of
building and discarding one on every embedding (OPT-2). ``compute_embeddings``
sends all texts in a single batched request; ``compute_embedding`` is the
single-text convenience wrapper.
"""

from __future__ import annotations

from functools import lru_cache

import voyageai


@lru_cache(maxsize=1)
def _client() -> voyageai.AsyncClient:  # type: ignore[name-defined]
    """Return the process-wide Voyage async client (constructed once)."""
    return voyageai.AsyncClient()  # type: ignore[attr-defined]


async def compute_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed ``texts`` in a single batched Voyage request.

    One network round-trip regardless of batch size, instead of one per item.
    """
    if not texts:
        return []
    from inkprint.core.config import get_settings

    settings = get_settings()
    result = await _client().embed(list(texts), model=settings.voyage_model)
    return [list(e) for e in result.embeddings]


async def compute_embedding(text: str) -> list[float]:
    """Compute an embedding for a single text (default model: voyage-3-lite)."""
    embeddings = await compute_embeddings([text])
    return embeddings[0]
