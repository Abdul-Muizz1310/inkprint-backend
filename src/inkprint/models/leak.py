"""ORM models for leak-scan jobs and their per-corpus results.

``leak_scan_jobs`` (added in ``0003``) is the pollable async job the API
returns and the client polls/streams. ``leak_scans`` (from ``0001``) holds one
durable row per corpus result, linked back to its job via ``scan_id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON as SAJSON
from sqlalchemy import ForeignKey, Integer, Numeric, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from inkprint.models.base import Base


class LeakScanJob(Base):
    """An async leak-scan job spanning one or more corpora."""

    __tablename__ = "leak_scan_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True)
    certificate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("certificates.id"), nullable=False
    )
    corpora: Mapped[list[str]] = mapped_column(SAJSON(), nullable=False)
    status: Mapped[str] = mapped_column(Text(), nullable=False, server_default="pending")
    hit_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    # Per-corpus result summaries, surfaced verbatim to pollers.
    results: Mapped[list[dict[str, Any]]] = mapped_column(SAJSON(), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LeakScanResult(Base):
    """One durable per-corpus result row for a finished scan."""

    __tablename__ = "leak_scans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True)
    scan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("leak_scan_jobs.id"), nullable=True
    )
    certificate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("certificates.id"), nullable=False
    )
    corpus: Mapped[str] = mapped_column(Text(), nullable=False)
    snapshot: Mapped[str | None] = mapped_column(Text(), nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    hits: Mapped[list[dict[str, Any]]] = mapped_column(SAJSON(), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
