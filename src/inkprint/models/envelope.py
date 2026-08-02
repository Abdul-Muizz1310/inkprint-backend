"""ORM model for signed dossier envelopes.

Mirrors the ``dossier_envelopes`` table from ``alembic/versions/0002``. The
JSON/array columns use Postgres-native types with a SQLite-compatible variant
so the schema works on both engines.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, LargeBinary, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from inkprint.models.base import Base


class DossierEnvelope(Base):
    """A signed bundle manifest tying evidence certs to a dossier."""

    __tablename__ = "dossier_envelopes"

    dossier_id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True)
    envelope_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    envelope_signature: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence_cert_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid()).with_variant(JSON(), "sqlite"), nullable=False
    )
    debate_transcript_hash: Mapped[str] = mapped_column(Text(), nullable=False)
    perf_receipt_hash: Mapped[str] = mapped_column(Text(), nullable=False)
    # Part of the idempotency fingerprint (migration 0005): a re-submission with
    # the same metadata must be recognised as identical after a restart.
    envelope_metadata: Mapped[dict[str, str] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    # The exact bytes that were signed, kept verbatim so verification never has
    # to re-derive them from a timestamp (migration 0005).
    canonical_bundle: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
