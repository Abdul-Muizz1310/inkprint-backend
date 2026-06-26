"""Repository for certificates and derivative links.

Records cross the boundary as dicts shaped like the legacy in-memory store
(keys: ``id``, ``author``, ``text``, ``content_hash``, ``simhash``,
``embedding`` as a ``list[float]``, ``content_len``, ``language``,
``issued_at``, ``signature``, ``manifest``, ``storage_key``, ``metadata``).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkprint.fingerprint.compare import _cosine_similarity
from inkprint.models.certificate import Certificate, DerivativeLink


def _to_record(model: Certificate) -> dict[str, Any]:
    """Map a :class:`Certificate` row back to a service record dict."""
    return {
        "id": str(model.id),
        "author": model.author,
        "text": model.text,
        "content_hash": model.content_hash,
        "simhash": int(model.simhash),
        "embedding": json.loads(model.embedding),
        "content_len": model.content_len,
        "language": model.language,
        "issued_at": model.issued_at,
        "signature": model.signature,
        "manifest": model.manifest,
        "storage_key": model.storage_key,
        "metadata": model.cert_metadata,
    }


def _to_model(record: dict[str, Any]) -> Certificate:
    """Map a service record dict to a new :class:`Certificate` row."""
    return Certificate(
        id=UUID(str(record["id"])),
        author=record["author"],
        text=record["text"],
        content_hash=record["content_hash"],
        simhash=str(record["simhash"]),
        embedding=json.dumps(record["embedding"]),
        content_len=record["content_len"],
        language=record["language"],
        issued_at=record["issued_at"],
        signature=record["signature"],
        manifest=record["manifest"],
        storage_key=record.get("storage_key"),
        cert_metadata=record.get("metadata"),
    )


async def add(session: AsyncSession, record: dict[str, Any]) -> dict[str, Any]:
    """Insert a certificate. Returns the same record for convenience."""
    session.add(_to_model(record))
    await session.flush()
    return record


async def add_many(session: AsyncSession, records: list[dict[str, Any]]) -> None:
    """Insert many certificates in one flush (atomic within the session)."""
    session.add_all([_to_model(r) for r in records])
    await session.flush()


async def get(session: AsyncSession, cert_id: str) -> dict[str, Any] | None:
    """Fetch a certificate by UUID string, or None."""
    model = await session.get(Certificate, UUID(cert_id))
    return _to_record(model) if model is not None else None


async def exists(session: AsyncSession, cert_id: str) -> bool:
    """Return whether a certificate with this id exists."""
    return await session.get(Certificate, UUID(cert_id)) is not None


async def count(session: AsyncSession) -> int:
    """Return the total number of certificates (test/diagnostic helper)."""
    result = await session.scalars(select(Certificate.id))
    return len(result.all())


async def search_exact(session: AsyncSession, content_hash: str) -> list[dict[str, Any]]:
    """Return certificates whose content hash matches exactly."""
    rows = (
        await session.scalars(select(Certificate).where(Certificate.content_hash == content_hash))
    ).all()
    return [{"id": str(r.id), "author": r.author, "score": 1.0} for r in rows]


async def search_semantic(
    session: AsyncSession, query_embedding: list[float], *, limit: int = 10
) -> list[dict[str, Any]]:
    """Rank certificates by cosine similarity to ``query_embedding``.

    Pure-Python cosine over the stored JSON embeddings. Entries with
    non-positive similarity (e.g. the zero-vector fallback when no embedding
    backend is configured) are dropped, so without real embeddings this
    returns nothing rather than arbitrary noise. A pgvector ANN index is an
    optional production optimization, not required for correctness.
    """
    rows = (await session.scalars(select(Certificate))).all()
    scored: list[dict[str, Any]] = []
    for r in rows:
        embedding = json.loads(r.embedding)
        score = _cosine_similarity(query_embedding, embedding)
        if score > 0.0:
            scored.append({"id": str(r.id), "author": r.author, "score": round(score, 6)})
    scored.sort(key=lambda e: e["score"], reverse=True)
    return scored[:limit]


async def add_derivative_link(
    session: AsyncSession,
    *,
    parent_id: UUID,
    child_id: UUID,
    hamming: int,
    cosine: float,
    verdict: str,
) -> None:
    """Record a derivative relationship between two existing certificates."""
    session.add(
        DerivativeLink(
            parent_id=parent_id,
            child_id=child_id,
            hamming=hamming,
            cosine=cosine,
            verdict=verdict,
        )
    )
    await session.flush()


async def list_derivative_links(session: AsyncSession, parent_id: UUID) -> list[dict[str, Any]]:
    """List derivative links recorded against a parent certificate."""
    rows = (
        await session.scalars(select(DerivativeLink).where(DerivativeLink.parent_id == parent_id))
    ).all()
    return [
        {
            "parent_id": str(r.parent_id),
            "child_id": str(r.child_id),
            "hamming": r.hamming,
            "cosine": float(r.cosine),
            "verdict": r.verdict,
        }
        for r in rows
    ]
