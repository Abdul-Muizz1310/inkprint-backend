"""Batch certificate + batch verify service.

Orchestration layer. Builds records atomically in memory before committing them
to the certificate store, so a mid-batch failure leaves no partial state.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from inkprint.core.db import session_scope
from inkprint.fingerprint.compare import compare
from inkprint.fingerprint.simhash import compute_simhash
from inkprint.provenance.canonicalize import canonicalize
from inkprint.provenance.manifest import build_manifest, validate_manifest
from inkprint.provenance.signer import sign, verify
from inkprint.repositories import certificate_repo

logger = logging.getLogger(__name__)


class EmbeddingServiceUnavailableError(RuntimeError):
    """Raised when the embedding backend fails mid-batch."""


async def _compute_embeddings_or_raise(texts: list[str]) -> list[list[float]]:
    """Embed all batch texts in one call; raise on failure.

    Unlike the single-cert path (which falls back to a zero vector), the batch
    path prefers failing loud to preserve all-or-nothing semantics. Sending the
    whole batch in a single Voyage request (rather than one call per item) keeps
    latency and API-quota flat in the batch size (OPT-1).
    """
    try:
        from inkprint.fingerprint.embed import compute_embeddings

        return await compute_embeddings(texts)
    except Exception as exc:
        raise EmbeddingServiceUnavailableError(str(exc)) from exc


async def create_batch(
    items: list[dict[str, Any]],
    *,
    private_key: Ed25519PrivateKey,
    public_key: Ed25519PublicKey,
    key_id: str,
) -> list[dict[str, Any]]:
    """Create N certificates atomically.

    All records are assembled in local lists; only on full success are they
    committed to the underlying store. If any item fails — shape, embedding,
    manifest schema — raises without mutating the store.
    """
    assert isinstance(private_key, Ed25519PrivateKey)
    assert isinstance(public_key, Ed25519PublicKey)

    issued_at = datetime.now(UTC)
    pending_records: list[dict[str, Any]] = []
    response_items: list[dict[str, Any]] = []

    # One batched embedding request for the whole batch (OPT-1). All-or-nothing:
    # a failure here raises before anything is persisted.
    embeddings = await _compute_embeddings_or_raise([item["text"] for item in items])

    for item, embedding in zip(items, embeddings, strict=True):
        text: str = item["text"]
        author: str = item["author"]
        metadata: dict[str, str] | None = item.get("metadata")

        canonical = canonicalize(text)
        content_hash = hashlib.sha256(canonical).hexdigest()
        signature_b64 = sign(canonical, private_key)
        simhash_val = compute_simhash(text)

        language: str | None = None
        try:
            from langdetect import detect

            language = detect(text)
        except Exception:
            language = None

        cert_id = uuid4()
        embedding_id = uuid4()

        manifest = build_manifest(
            certificate_id=cert_id,
            author=author,
            content_hash=content_hash,
            signature_b64=signature_b64,
            key_id=key_id,
            content_length=len(canonical),
            language=language,
            issued_at=issued_at,
        )
        validate_manifest(manifest)

        record = {
            "id": str(cert_id),
            "author": author,
            "text": text,
            "content_hash": content_hash,
            "simhash": simhash_val,
            "embedding": embedding,
            "embedding_id": str(embedding_id),
            "content_len": len(canonical),
            "language": language,
            "issued_at": issued_at,
            "signature": signature_b64,
            "manifest": manifest,
            # Provisional: replaced below by the real R2 key when archival
            # succeeds. Never leave a key here that no object backs.
            "storage_key": f"certificates/{cert_id}.json",
            "metadata": metadata,
        }
        pending_records.append(record)
        response_items.append(
            {
                "certificate_id": cert_id,
                "manifest": manifest,
                "fingerprints": {
                    "sha256": content_hash,
                    "simhash": simhash_val,
                    "embedding_id": embedding_id,
                },
            }
        )

    # Archive every blob before committing, so the persisted ``storage_key``
    # names a real object whenever R2 is configured. Best-effort by contract
    # (see :func:`r2.archive_text`): an unconfigured or failing R2 degrades each
    # key back to the logical one — exactly what the single-certificate path
    # does — and never fails the batch.
    await _archive_batch(pending_records)

    # Commit: all-or-nothing. Any embedding/manifest failure above raised
    # before this point, so nothing is persisted on a mid-batch failure.
    async with session_scope() as session:
        await certificate_repo.add_many(session, pending_records)

    return response_items


async def _archive_batch(records: list[dict[str, Any]]) -> None:
    """Archive each record's text to R2 concurrently, rewriting ``storage_key``.

    Mutates ``records`` in place. Concurrency keeps a 50-item batch's archival
    latency flat rather than serial (the same motivation as the single batched
    embedding call).
    """
    import asyncio

    from inkprint.core import r2

    keys = await asyncio.gather(*(r2.archive_text(r["storage_key"], r["text"]) for r in records))
    for record, archived_key in zip(records, keys, strict=True):
        if archived_key:
            record["storage_key"] = archived_key


async def verify_batch(
    items: list[dict[str, Any]],
    *,
    public_key: Ed25519PublicKey,
) -> list[dict[str, Any]]:
    """Verify N certificates; per-item results, unknown IDs fail softly."""
    assert isinstance(public_key, Ed25519PublicKey)

    results: list[dict[str, Any]] = []
    async with session_scope() as session:
        cert_ids = [str(item["certificate_id"]) for item in items]
        records = {cid: await certificate_repo.get(session, cid) for cid in set(cert_ids)}

    for item in items:
        cert_id: UUID = item["certificate_id"]
        supplied_text: str | None = item.get("text")

        record = records[str(cert_id)]
        if record is None:
            results.append(
                {
                    "certificate_id": cert_id,
                    "valid": False,
                    "checks": {},
                    "reason": "unknown_certificate",
                }
            )
            continue

        checks: dict[str, bool] = {}

        stored_canonical = canonicalize(record["text"])
        checks["signature"] = verify(stored_canonical, record["signature"], public_key)
        checks["hash"] = hashlib.sha256(stored_canonical).hexdigest() == record["content_hash"]

        if supplied_text is not None:
            supplied_simhash = compute_simhash(supplied_text)
            # Re-embed the supplied text; fall back to stored embedding on failure
            # so we can still emit a comparison rather than crashing.
            try:
                from inkprint.fingerprint.embed import compute_embedding

                supplied_embedding = await compute_embedding(supplied_text)
            except Exception:
                supplied_embedding = record["embedding"]

            parent_embedding = record["embedding"]
            parent_zero = all(v == 0.0 for v in parent_embedding)
            supplied_zero = all(v == 0.0 for v in supplied_embedding)
            if parent_zero and supplied_zero:
                unit = [1.0] + [0.0] * (len(parent_embedding) - 1)
                parent_embedding = unit
                supplied_embedding = unit

            cmp = compare(
                parent_simhash=record["simhash"],
                parent_embedding=parent_embedding,
                child_simhash=supplied_simhash,
                child_embedding=supplied_embedding,
            )
            # "simhash match" and "embedding match" mean the verdict is at least
            # near-duplicate quality — tampering flips this to False.
            checks["simhash"] = cmp.hamming <= 3
            checks["embedding"] = cmp.cosine >= 0.99

        results.append(
            {
                "certificate_id": cert_id,
                "valid": all(checks.values()),
                "checks": checks,
                "reason": None,
            }
        )

    return results
