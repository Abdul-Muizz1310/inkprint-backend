"""Pydantic models for batch certificate + batch verify endpoints."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BatchCertificateItem(BaseModel):
    """One item in a batch-create request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=1_000_000)
    author: str = Field(min_length=1)
    metadata: dict[str, str] | None = None


class BatchCertificateCreateRequest(BaseModel):
    """Body for POST /certificates/batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[BatchCertificateItem] = Field(min_length=1, max_length=50)


class BatchFingerprints(BaseModel):
    """Fingerprint triple attached to each batch-created certificate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha256: str
    simhash: int
    embedding_id: UUID


class BatchCertificateRecord(BaseModel):
    """One certificate in the batch response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: UUID
    manifest: dict[str, Any]
    fingerprints: BatchFingerprints


class BatchCertificateResponse(BaseModel):
    """Response body for POST /certificates/batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificates: list[BatchCertificateRecord]


class BatchVerifyItem(BaseModel):
    """One item in a batch-verify request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: UUID
    text: str | None = Field(default=None, max_length=1_000_000)


class BatchVerifyRequest(BaseModel):
    """Body for POST /verify/batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[BatchVerifyItem] = Field(min_length=1, max_length=50)


class BatchVerifyItemResult(BaseModel):
    """Per-item result in a batch-verify response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: UUID
    valid: bool
    checks: dict[str, bool]
    reason: str | None = None


class BatchVerifyResponse(BaseModel):
    """Response body for POST /verify/batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: list[BatchVerifyItemResult]
