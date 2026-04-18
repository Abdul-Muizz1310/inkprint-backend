"""Dossier envelope service — pure orchestration around envelope_builder + signer."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from inkprint.provenance.envelope_builder import (
    build_envelope_manifest,
    canonical_bundle_bytes,
)
from inkprint.provenance.signer import sign
from inkprint.services import certificate_service


class UnknownCertificateError(Exception):
    """Raised when an evidence cert id does not resolve in the cert store."""

    def __init__(self, certificate_id: UUID) -> None:
        super().__init__(f"Unknown certificate: {certificate_id}")
        self.certificate_id = certificate_id


class EnvelopeConflictError(Exception):
    """Raised when a dossier_id already exists with a different bundle."""


# In-memory envelope store, keyed by str(dossier_id). Mirrors the pattern used
# by certificate_service and leak_service. The alembic migration defines the
# persistent schema for future DB-backed replacement.
_envelopes: dict[str, dict[str, Any]] = {}


def reset_store() -> None:
    """Clear the in-memory envelope store (tests)."""
    _envelopes.clear()


def _bundle_fingerprint(
    *,
    evidence_cert_ids: list[UUID],
    debate_transcript_hash: str,
    perf_receipt_hash: str,
    metadata: dict[str, str] | None,
) -> tuple[tuple[str, ...], str, str, tuple[tuple[str, str], ...]]:
    """Return a hashable representation of the non-time bundle components."""
    return (
        tuple(str(cid) for cid in evidence_cert_ids),
        debate_transcript_hash,
        perf_receipt_hash,
        tuple(sorted((metadata or {}).items())),
    )


def get_envelope(dossier_id: str) -> dict[str, Any] | None:
    """Look up an envelope by dossier_id string."""
    return _envelopes.get(dossier_id)


def create_envelope(
    *,
    dossier_id: UUID,
    evidence_cert_ids: list[UUID],
    debate_transcript_hash: str,
    perf_receipt_hash: str,
    metadata: dict[str, str] | None,
    private_key: Ed25519PrivateKey,
    key_id: str,
) -> dict[str, Any]:
    """Build, sign, and persist a dossier envelope.

    Raises UnknownCertificateError on missing evidence cert, or
    EnvelopeConflictError when a different bundle was already signed for the
    same dossier_id. Re-submitting identical inputs returns the stored record.
    """
    # 1. Validate all evidence cert ids exist.
    for cid in evidence_cert_ids:
        if certificate_service.get_certificate(str(cid)) is None:
            raise UnknownCertificateError(cid)

    # 2. Idempotency / conflict check.
    existing = _envelopes.get(str(dossier_id))
    if existing is not None:
        new_fp = _bundle_fingerprint(
            evidence_cert_ids=evidence_cert_ids,
            debate_transcript_hash=debate_transcript_hash,
            perf_receipt_hash=perf_receipt_hash,
            metadata=metadata,
        )
        if existing["_fingerprint"] == new_fp:
            return existing
        raise EnvelopeConflictError("Dossier already envelope-signed with different bundle")

    # 3. Build canonical bytes and sign.
    issued_at = datetime.now(UTC)
    canonical = canonical_bundle_bytes(
        dossier_id=dossier_id,
        evidence_cert_ids=evidence_cert_ids,
        debate_transcript_hash=debate_transcript_hash,
        perf_receipt_hash=perf_receipt_hash,
        metadata=metadata,
        issued_at=issued_at,
    )
    bundle_hash_hex = hashlib.sha256(canonical).hexdigest()
    signature_b64 = sign(canonical, private_key)

    # 4. Build manifest.
    manifest = build_envelope_manifest(
        dossier_id=dossier_id,
        evidence_cert_ids=evidence_cert_ids,
        debate_transcript_hash=debate_transcript_hash,
        perf_receipt_hash=perf_receipt_hash,
        bundle_hash_hex=bundle_hash_hex,
        signature_b64=signature_b64,
        key_id=key_id,
        issued_at=issued_at,
    )

    record: dict[str, Any] = {
        "envelope_id": dossier_id,
        "envelope_manifest": manifest,
        "envelope_signature": signature_b64,
        "canonical_bundle": canonical,
        "created_at": issued_at,
        "_fingerprint": _bundle_fingerprint(
            evidence_cert_ids=evidence_cert_ids,
            debate_transcript_hash=debate_transcript_hash,
            perf_receipt_hash=perf_receipt_hash,
            metadata=metadata,
        ),
    }
    _envelopes[str(dossier_id)] = record
    return record
