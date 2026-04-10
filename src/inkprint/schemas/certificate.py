"""Pydantic request/response models for the certificate API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CertificateCreate(BaseModel):
    """Request body for POST /certificates."""

    text: str
    author: str
    metadata: dict | None = None

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("text must not be empty")
        return v

    @field_validator("author")
    @classmethod
    def author_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("author must not be empty")
        return v


class CertificateResponse(BaseModel):
    """Response body for a certificate."""

    id: str
    author: str
    content_hash: str
    simhash: int
    content_len: int
    language: str | None
    issued_at: datetime
    signature: str
    manifest: dict
    storage_key: str


class VerifyRequest(BaseModel):
    """Request body for POST /verify."""

    manifest: dict
    text: str | None = None

    @field_validator("manifest")
    @classmethod
    def manifest_not_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("manifest must not be empty")
        return v


class VerifyResponse(BaseModel):
    """Response body for POST /verify."""

    valid: bool
    checks: dict
    warnings: list[str] = Field(default_factory=list)


class DiffRequest(BaseModel):
    """Request body for POST /diff."""

    parent_id: UUID
    text: str


class DiffResponse(BaseModel):
    """Response body for POST /diff."""

    hamming: int
    cosine: float
    verdict: str
    overlap_pct: int
    changed_spans: list = Field(default_factory=list)


class LeakScanRequest(BaseModel):
    """Request body for POST /leak-scan."""

    certificate_id: UUID
    corpora: list[str] | None = None


class LeakScanResponse(BaseModel):
    """Response body for POST /leak-scan."""

    scan_id: UUID
    status: str


class SearchResponse(BaseModel):
    """Response body for GET /search."""

    results: list
    total: int
