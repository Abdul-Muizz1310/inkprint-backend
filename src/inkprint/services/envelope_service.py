"""Dossier envelope service — orchestration around envelope_builder + signer.

Pure bundle/manifest construction lives in :mod:`inkprint.provenance.envelope_builder`;
persistence is delegated to :mod:`inkprint.repositories.envelope_repo` via a committed
:func:`session_scope`, the same shape the certificate and leak services use.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from inkprint.core.db import session_scope
from inkprint.provenance.envelope_builder import (
    build_envelope_manifest,
    canonical_bundle_bytes,
    validate_envelope_manifest,
)
from inkprint.provenance.signer import sign
from inkprint.repositories import envelope_repo
from inkprint.services import certificate_service


class UnknownCertificateError(Exception):
    """Raised when an evidence cert id does not resolve in the cert store."""

    def __init__(self, certificate_id: UUID) -> None:
        super().__init__(f"Unknown certificate: {certificate_id}")
        self.certificate_id = certificate_id


class EnvelopeConflictError(Exception):
    """Raised when a dossier_id already exists with a different bundle."""


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


def _record_fingerprint(
    record: dict[str, Any],
) -> tuple[tuple[str, ...], str, str, tuple[tuple[str, str], ...]]:
    """Rebuild the fingerprint of a stored envelope.

    Derived from persisted columns only, so idempotency and conflict detection
    survive a restart — they used to depend on a value kept in process memory.
    """
    return _bundle_fingerprint(
        evidence_cert_ids=list(record["evidence_cert_ids"]),
        debate_transcript_hash=record["debate_transcript_hash"],
        perf_receipt_hash=record["perf_receipt_hash"],
        metadata=record["metadata"],
    )


async def get_envelope(dossier_id: str) -> dict[str, Any] | None:
    """Look up a persisted envelope by dossier_id string."""
    async with session_scope() as session:
        return await envelope_repo.get(session, dossier_id)


async def create_envelope(
    *,
    dossier_id: UUID,
    evidence_cert_ids: list[UUID],
    debate_transcript_hash: str,
    perf_receipt_hash: str,
    metadata: dict[str, str] | None,
    private_key: Ed25519PrivateKey,
    key_id: str,
) -> dict[str, Any]:
    """Build, sign, validate, and persist a dossier envelope.

    Raises UnknownCertificateError on missing evidence cert, or
    EnvelopeConflictError when a different bundle was already signed for the
    same dossier_id. Re-submitting identical inputs returns the stored record.

    The envelope row lands in the ``dossier_envelopes`` table, so a signed
    envelope survives a container restart.
    """
    # 1. Validate all evidence cert ids exist.
    for cid in evidence_cert_ids:
        if await certificate_service.get_certificate(str(cid)) is None:
            raise UnknownCertificateError(cid)

    # 2. Idempotency / conflict check against storage.
    existing = await get_envelope(str(dossier_id))
    if existing is not None:
        new_fp = _bundle_fingerprint(
            evidence_cert_ids=evidence_cert_ids,
            debate_transcript_hash=debate_transcript_hash,
            perf_receipt_hash=perf_receipt_hash,
            metadata=metadata,
        )
        if _record_fingerprint(existing) == new_fp:
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

    # 4. Build the manifest and validate it against the committed JSON Schema
    #    *before* persisting — the same guarantee the certificate paths give.
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
    validate_envelope_manifest(manifest)

    record: dict[str, Any] = {
        "envelope_id": dossier_id,
        "envelope_manifest": manifest,
        "envelope_signature": signature_b64,
        "evidence_cert_ids": list(evidence_cert_ids),
        "debate_transcript_hash": debate_transcript_hash,
        "perf_receipt_hash": perf_receipt_hash,
        "metadata": metadata,
        "canonical_bundle": canonical,
        "created_at": issued_at,
    }
    async with session_scope() as session:
        await envelope_repo.add(session, record)
    return record
