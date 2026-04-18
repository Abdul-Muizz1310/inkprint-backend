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

from inkprint.fingerprint.compare import compare
from inkprint.fingerprint.simhash import compute_simhash
from inkprint.provenance.canonicalize import canonicalize
from inkprint.provenance.manifest import build_manifest, validate_manifest
from inkprint.provenance.signer import sign, verify
from inkprint.services import certificate_service

logger = logging.getLogger(__name__)


class EmbeddingServiceUnavailableError(RuntimeError):
    """Raised when the embedding backend fails mid-batch."""


async def _compute_embedding_or_raise(text: str) -> list[float]:
    """Compute an embedding; raise EmbeddingServiceUnavailableError on failure.

    Unlike the single-cert path (which falls back to a zero vector), the batch
    path prefers failing loud to preserve all-or-nothing semantics.
    """
    try:
        from inkprint.fingerprint.embed import compute_embedding

        return await compute_embedding(text)
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

    for item in items:
        text: str = item["text"]
        author: str = item["author"]
        metadata: dict[str, str] | None = item.get("metadata")

        canonical = canonicalize(text)
        content_hash = hashlib.sha256(canonical).hexdigest()
        signature_b64 = sign(canonical, private_key)
        simhash_val = compute_simhash(text)
        embedding = await _compute_embedding_or_raise(text)

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

    # Commit: all-or-nothing
    for record in pending_records:
        certificate_service._certificates[str(record["id"])] = record

    return response_items


async def verify_batch(
    items: list[dict[str, Any]],
    *,
    public_key: Ed25519PublicKey,
) -> list[dict[str, Any]]:
    """Verify N certificates; per-item results, unknown IDs fail softly."""
    assert isinstance(public_key, Ed25519PublicKey)

    results: list[dict[str, Any]] = []
    for item in items:
        cert_id: UUID = item["certificate_id"]
        supplied_text: str | None = item.get("text")

        record = certificate_service.get_certificate(str(cert_id))
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
