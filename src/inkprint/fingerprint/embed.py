"""Voyage AI embedding computation.

The Voyage async client is constructed once per process (``_client``) and reused
across calls so we keep the underlying TLS/connection pool warm instead of
building and discarding one on every embedding (OPT-2). ``compute_embeddings``
sends all texts in a single batched request; ``compute_embedding`` is the
single-text convenience wrapper.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Final

import voyageai

# The SDK's default request timeout is 600 s. Embeddings are best-effort (the
# callers fall back to ZERO_EMBEDDING), so a rate-limited or hung call must fail
# fast rather than eat the caller's budget — bastion gives a batch call 60 s.
EMBED_TIMEOUT_S: Final = 15.0

# The stored fallback when no embedding could be computed: it has no positive
# cosine similarity with anything, so semantic search simply never ranks it.
EMBEDDING_FALLBACK_DIM: Final = 768


def zero_embedding() -> list[float]:
    """The fallback vector stored when the embedding call fails."""
    return [0.0] * EMBEDDING_FALLBACK_DIM


@lru_cache(maxsize=1)
def _client() -> voyageai.AsyncClient:  # type: ignore[name-defined]
    """Return the process-wide Voyage async client (constructed once).

    ``max_retries=0`` (one attempt: a 429 fails at once instead of backing off
    for up to a minute) and a short timeout — see ``EMBED_TIMEOUT_S``.
    """
    return voyageai.AsyncClient(max_retries=0, timeout=EMBED_TIMEOUT_S)  # type: ignore[attr-defined]


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
