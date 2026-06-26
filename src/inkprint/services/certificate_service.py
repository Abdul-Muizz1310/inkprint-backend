"""Certificate service — domain logic over the DB-backed repository.

Pure provenance/fingerprint logic (canonicalize, sign, fingerprint, manifest)
lives here and in :mod:`inkprint.provenance`/:mod:`inkprint.fingerprint`;
persistence is delegated to :mod:`inkprint.repositories.certificate_repo` via a
committed :func:`session_scope`.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from inkprint.core.db import session_scope
from inkprint.fingerprint.compare import compare
from inkprint.fingerprint.simhash import compute_simhash
from inkprint.provenance.canonicalize import canonicalize
from inkprint.provenance.manifest import build_manifest, validate_manifest
from inkprint.provenance.signer import sign, verify
from inkprint.repositories import certificate_repo

logger = logging.getLogger(__name__)


async def _compute_embedding_or_zero(text: str) -> list[float]:
    """Compute an embedding, falling back to a zero vector on any failure."""
    try:
        from inkprint.fingerprint.embed import compute_embedding

        return await compute_embedding(text)
    except Exception:
        logger.debug("Embedding computation failed; using zero vector fallback")
        return [0.0] * 768


def _detect_language(text: str) -> str | None:
    """Best-effort language detection; None when unavailable."""
    try:
        from langdetect import detect

        return str(detect(text))
    except Exception:
        return None


async def create_certificate(
    text: str,
    author: str,
    metadata: dict[str, Any] | None,
    *,
    private_key: object,
    public_key: object,
    key_id: str,
) -> dict[str, Any]:
    """Create a certificate: canonicalize, hash, sign, fingerprint, persist."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    assert isinstance(private_key, Ed25519PrivateKey)
    assert isinstance(public_key, Ed25519PublicKey)

    cert_id = uuid4()
    canonical = canonicalize(text)
    content_hash = hashlib.sha256(canonical).hexdigest()
    signature_b64 = sign(canonical, private_key)
    simhash_val = compute_simhash(text)
    embedding = await _compute_embedding_or_zero(text)
    language = _detect_language(text)
    issued_at = datetime.now(UTC)

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
        "content_len": len(canonical),
        "language": language,
        "issued_at": issued_at,
        "signature": signature_b64,
        "manifest": manifest,
        "storage_key": f"certificates/{cert_id}.json",
        "metadata": metadata,
    }
    async with session_scope() as session:
        await certificate_repo.add(session, record)
    return record


async def get_certificate(cert_id: str) -> dict[str, Any] | None:
    """Look up a certificate by UUID string."""
    async with session_scope() as session:
        return await certificate_repo.get(session, cert_id)


def verify_certificate(
    manifest: dict[str, Any],
    text: str | None,
    *,
    public_key: object,
) -> dict[str, Any]:
    """Verify a manifest's signature and optionally check text hash."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    assert isinstance(public_key, Ed25519PublicKey)

    checks: dict[str, bool] = {}
    warnings: list[str] = []

    sig_block = manifest.get("signature", {})
    sig_value = sig_block.get("value", "")

    hash_assertion = None
    for a in manifest.get("assertions", []):
        if a["label"] == "c2pa.hash.data":
            hash_assertion = a
            break

    if hash_assertion and sig_value:
        manifest_hash = hash_assertion["data"]["hash"]
        if text is not None:
            canonical = canonicalize(text)
            content_hash = hashlib.sha256(canonical).hexdigest()
            checks["hash"] = content_hash == manifest_hash
            checks["signature"] = verify(canonical, sig_value, public_key)
        else:
            # Without original text, cryptographic verification is impossible.
            # Never report valid=True without actual crypto verification.
            checks["signature"] = False
            checks["hash"] = False
            warnings.append("Text not provided; cannot verify signature or hash")
    else:
        checks["signature"] = False
        checks["hash"] = False

    valid = all(checks.values())
    return {"valid": valid, "checks": checks, "warnings": warnings}


async def diff_certificate(
    parent_id: str,
    text: str,
) -> dict[str, Any] | None:
    """Compare new text against a parent certificate's fingerprints."""
    parent = await get_certificate(parent_id)
    if parent is None:
        return None

    child_simhash = compute_simhash(text)
    child_embedding = await _compute_embedding_or_zero(text)
    parent_embedding = parent["embedding"]

    # When both embeddings are zero vectors (fallback), use unit vectors
    # so cosine similarity reflects the simhash signal rather than producing 0.0.
    parent_is_zero = all(v == 0.0 for v in parent_embedding)
    child_is_zero = all(v == 0.0 for v in child_embedding)
    if parent_is_zero and child_is_zero:
        unit = [1.0] + [0.0] * (len(parent_embedding) - 1)
        parent_embedding = unit
        child_embedding = unit

    result = compare(
        parent_simhash=parent["simhash"],
        parent_embedding=parent_embedding,
        child_simhash=child_simhash,
        child_embedding=child_embedding,
    )

    return {
        "hamming": result.hamming,
        "cosine": result.cosine,
        "verdict": result.verdict,
        "overlap_pct": result.overlap_pct,
        "changed_spans": [],
    }


async def search_certificates(text: str, mode: str) -> dict[str, Any]:
    """Search certificates by hash (exact) or embedding (semantic).

    Exact mode matches the canonical SHA-256. Semantic mode embeds the query
    and ranks stored certificates by cosine similarity; without an embedding
    backend the query vector is zero and semantic search returns nothing.
    """
    async with session_scope() as session:
        if mode == "exact":
            canonical = canonicalize(text)
            content_hash = hashlib.sha256(canonical).hexdigest()
            results = await certificate_repo.search_exact(session, content_hash)
        elif mode == "semantic":
            query_embedding = await _compute_embedding_or_zero(text)
            results = await certificate_repo.search_semantic(session, query_embedding)
        else:
            results = []

    return {"results": results, "total": len(results)}
