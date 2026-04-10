"""Initial schema — certificates, derivative_links, leak_scans.

Revision ID: 0001
Revises:
Create Date: 2026-04-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "certificates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("simhash", sa.BigInteger(), nullable=False),
        sa.Column(
            "embedding", sa.Text(), nullable=False
        ),  # stored as JSON array; pgvector via raw SQL
        sa.Column("content_len", sa.Integer(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
    )
    op.create_index("ix_certificates_content_hash", "certificates", ["content_hash"])
    op.create_index("ix_certificates_author", "certificates", ["author"])

    op.create_table(
        "derivative_links",
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("certificates.id"), primary_key=True),
        sa.Column("child_id", sa.Uuid(), sa.ForeignKey("certificates.id"), primary_key=True),
        sa.Column("hamming", sa.Integer(), nullable=False),
        sa.Column("cosine", sa.Numeric(4, 3), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
    )

    op.create_table(
        "leak_scans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("certificate_id", sa.Uuid(), sa.ForeignKey("certificates.id")),
        sa.Column("corpus", sa.Text(), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("hits", sa.JSON(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("leak_scans")
    op.drop_table("derivative_links")
    op.drop_table("certificates")
