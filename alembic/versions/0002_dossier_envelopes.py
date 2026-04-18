"""Dossier envelopes — signed bundle manifests.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dossier_envelopes",
        sa.Column("dossier_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "envelope_manifest",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("envelope_signature", sa.Text(), nullable=False),
        sa.Column(
            "evidence_cert_ids",
            postgresql.ARRAY(sa.Uuid()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("debate_transcript_hash", sa.Text(), nullable=False),
        sa.Column("perf_receipt_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("dossier_envelopes")
