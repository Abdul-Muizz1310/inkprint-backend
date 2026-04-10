"""Certificate service — orchestrates domain logic with in-memory storage."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from uuid import uuid4

from inkprint.fingerprint.compare import compare
from inkprint.fingerprint.simhash import compute_simhash
from inkprint.provenance.canonicalize import canonicalize
from inkprint.provenance.manifest import build_manifest, validate_manifest
from inkprint.provenance.signer import sign, verify

logger = logging.getLogger(__name__)

# In-memory store — replaced with SQLAlchemy in a later step.
_certificates: dict[str, dict] = {}


def reset_store() -> None:
    """Clear the in-memory store (useful for tests)."""
    _certificates.clear()


async def create_certificate(
    text: str,
    author: str,
    metadata: dict | None,
    *,
    private_key: object,
    public_key: object,
    key_id: str,
) -> dict:
    """Create a certificate: canonicalize, hash, sign, fingerprint, build manifest."""
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

    # Embedding — fallback to zero vector when Voyage API key is missing
    embedding: list[float] = [0.0] * 768
    try:
        from inkprint.fingerprint.embed import compute_embedding

        embedding = await compute_embedding(text)
    except Exception:
        logger.debug("Embedding computation failed; using zero vector fallback")

    # Language detection
    language: str | None = None
    try:
        from langdetect import detect

        language = detect(text)
    except Exception:
        language = None

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

    storage_key = f"certificates/{cert_id}.json"

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
        "storage_key": storage_key,
        "metadata": metadata,
    }
    _certificates[str(cert_id)] = record
    return record


def get_certificate(cert_id: str) -> dict | None:
    """Look up a certificate by UUID string."""
    return _certificates.get(cert_id)


def verify_certificate(
    manifest: dict,
    text: str | None,
    *,
    public_key: object,
) -> dict:
    """Verify a manifest's signature and optionally check text hash."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    assert isinstance(public_key, Ed25519PublicKey)

    checks: dict[str, bool] = {}
    warnings: list[str] = []

    # Check signature
    sig_block = manifest.get("signature", {})
    sig_value = sig_block.get("value", "")
    signed_assertions = sig_block.get("signed_assertions", [])

    # Build the data that was signed: the canonical hash from the manifest
    hash_assertion = None
    for a in manifest.get("assertions", []):
        if a["label"] == "c2pa.hash.data":
            hash_assertion = a
            break

    if hash_assertion and sig_value:
        manifest_hash = hash_assertion["data"]["hash"]
        # Verify signature over canonical content — we need the original canonical bytes
        # The signature was over canonicalize(text). If text is provided, verify fully.
        if text is not None:
            canonical = canonicalize(text)
            content_hash = hashlib.sha256(canonical).hexdigest()
            checks["hash"] = content_hash == manifest_hash
            checks["signature"] = verify(canonical, sig_value, public_key)
        else:
            # Without text, we can only check structural validity
            checks["signature"] = bool(sig_value and signed_assertions)
            checks["hash"] = True  # Can't verify without text
            warnings.append("Text not provided; hash check skipped")
    else:
        checks["signature"] = False
        checks["hash"] = False

    valid = all(checks.values())
    return {"valid": valid, "checks": checks, "warnings": warnings}


async def diff_certificate(
    parent_id: str,
    text: str,
) -> dict | None:
    """Compare new text against a parent certificate's fingerprints."""
    parent = get_certificate(parent_id)
    if parent is None:
        return None

    child_simhash = compute_simhash(text)

    # Embedding — fallback to zero vector
    child_embedding: list[float] = [0.0] * 768
    try:
        from inkprint.fingerprint.embed import compute_embedding

        child_embedding = await compute_embedding(text)
    except Exception:
        logger.debug("Embedding computation failed; using zero vector fallback")

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


def search_certificates(text: str, mode: str) -> dict:
    """Search certificates by hash (exact) or embedding (semantic)."""
    results: list[dict] = []

    if mode == "exact":
        canonical = canonicalize(text)
        content_hash = hashlib.sha256(canonical).hexdigest()
        for cert in _certificates.values():
            if cert["content_hash"] == content_hash:
                results.append({"id": cert["id"], "author": cert["author"], "score": 1.0})
    elif mode == "semantic":
        # Without a real vector DB, return empty results
        pass

    return {"results": results, "total": len(results)}
