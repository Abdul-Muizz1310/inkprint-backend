"""ORM models for certificates and their derivative links.

Mirrors the ``certificates`` and ``derivative_links`` tables created in
``alembic/versions/0001_initial.py``. Two columns absent from the original
migration are added in ``0003`` so the service can run without a Cloudflare R2
blob store: ``text`` (the canonical source, kept in-row for small documents)
and ``cert_metadata`` (free-form caller metadata). The ``embedding`` is stored
as a JSON-encoded float array in a ``Text`` column — pgvector is an optional
production index, not a hard requirement for storage or cosine ranking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON as SAJSON
from sqlalchemy import ForeignKey, Integer, Numeric, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from inkprint.models.base import Base


class Certificate(Base):
    """A signed content certificate with provenance + fingerprints."""

    __tablename__ = "certificates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True)
    author: Mapped[str] = mapped_column(Text(), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text(), nullable=False, server_default="")
    content_hash: Mapped[str] = mapped_column(Text(), nullable=False, index=True)
    # SimHash is a 64-bit *unsigned* value, which overflows a signed BigInteger
    # (max 2**63-1) on both SQLite and Postgres, so it is stored as a decimal
    # string and parsed back to int at the repository boundary.
    simhash: Mapped[str] = mapped_column(Text(), nullable=False)
    # JSON-encoded float array (length 768). Stored as Text for portability.
    embedding: Mapped[str] = mapped_column(Text(), nullable=False)
    content_len: Mapped[int] = mapped_column(Integer(), nullable=False)
    language: Mapped[str | None] = mapped_column(Text(), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    signature: Mapped[str] = mapped_column(Text(), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(SAJSON(), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(Text(), nullable=True)
    cert_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "cert_metadata", SAJSON(), nullable=True
    )


class DerivativeLink(Base):
    """A recorded derivative relationship between two certificates."""

    __tablename__ = "derivative_links"

    parent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("certificates.id"), primary_key=True
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("certificates.id"), primary_key=True
    )
    hamming: Mapped[int] = mapped_column(Integer(), nullable=False)
    cosine: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    verdict: Mapped[str] = mapped_column(Text(), nullable=False)
