"""Persisted certificate text + metadata and async leak-scan jobs.

Adds the columns and table the in-memory-to-DB cutover needs:
- ``certificates.text`` / ``certificates.cert_metadata`` so a certificate's
  source survives without a Cloudflare R2 blob store.
- ``leak_scan_jobs`` — the pollable async scan job (status lifecycle).
- ``leak_scans.scan_id`` — links a per-corpus result row back to its job.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "certificates",
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "certificates",
        sa.Column("cert_metadata", _JSON, nullable=True),
    )
    # SimHash is an unsigned 64-bit value that overflows a signed BigInteger;
    # store it as a decimal string (matches the ORM, parsed to int on read).
    op.alter_column(
        "certificates",
        "simhash",
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="simhash::text",
    )

    op.create_table(
        "leak_scan_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("certificate_id", sa.Uuid(), sa.ForeignKey("certificates.id"), nullable=False),
        sa.Column("corpora", _JSON, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("results", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "leak_scans",
        sa.Column("scan_id", sa.Uuid(), sa.ForeignKey("leak_scan_jobs.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leak_scans", "scan_id")
    op.drop_table("leak_scan_jobs")
    op.alter_column(
        "certificates",
        "simhash",
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="simhash::bigint",
    )
    op.drop_column("certificates", "cert_metadata")
    op.drop_column("certificates", "text")
