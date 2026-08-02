"""Repository for signed dossier envelopes.

Records cross the boundary as dicts keyed ``envelope_id``, ``envelope_manifest``,
``envelope_signature``, ``evidence_cert_ids``, ``debate_transcript_hash``,
``perf_receipt_hash``, ``metadata``, ``canonical_bundle``, ``created_at`` — so the
service stays ORM-agnostic.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from inkprint.models.envelope import DossierEnvelope


def _to_record(model: DossierEnvelope) -> dict[str, Any]:
    """Map a :class:`DossierEnvelope` row back to a service record dict."""
    return {
        "envelope_id": model.dossier_id,
        "envelope_manifest": model.envelope_manifest,
        "envelope_signature": model.envelope_signature,
        "evidence_cert_ids": [UUID(str(cid)) for cid in model.evidence_cert_ids],
        "debate_transcript_hash": model.debate_transcript_hash,
        "perf_receipt_hash": model.perf_receipt_hash,
        "metadata": model.envelope_metadata,
        "canonical_bundle": bytes(model.canonical_bundle),
        "created_at": model.created_at,
    }


async def add(session: AsyncSession, record: dict[str, Any]) -> dict[str, Any]:
    """Insert an envelope row. Returns the same record for convenience."""
    session.add(
        DossierEnvelope(
            dossier_id=record["envelope_id"],
            envelope_manifest=record["envelope_manifest"],
            envelope_signature=record["envelope_signature"],
            # Stored as JSON on SQLite, so serialize the ids as strings; the
            # Postgres UUID[] variant accepts them too.
            evidence_cert_ids=[str(cid) for cid in record["evidence_cert_ids"]],
            debate_transcript_hash=record["debate_transcript_hash"],
            perf_receipt_hash=record["perf_receipt_hash"],
            envelope_metadata=record.get("metadata"),
            canonical_bundle=record["canonical_bundle"],
            created_at=record["created_at"],
        )
    )
    await session.flush()
    return record


async def get(session: AsyncSession, dossier_id: str) -> dict[str, Any] | None:
    """Fetch an envelope by dossier UUID string, or None."""
    model = await session.get(DossierEnvelope, UUID(dossier_id))
    return _to_record(model) if model is not None else None
