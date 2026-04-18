"""Pydantic models for dossier envelope endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

HEX64_PATTERN = r"^[a-f0-9]{64}$"


class EnvelopeRequest(BaseModel):
    """Body for POST /dossiers/envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dossier_id: UUID
    evidence_cert_ids: list[UUID] = Field(min_length=1, max_length=50)
    debate_transcript_hash: str = Field(pattern=HEX64_PATTERN)
    perf_receipt_hash: str = Field(pattern=HEX64_PATTERN)
    metadata: dict[str, str] | None = None


class EnvelopeResponse(BaseModel):
    """Response body for POST /dossiers/envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope_id: UUID
    envelope_manifest: dict[str, Any]
    envelope_signature: str
    created_at: datetime
