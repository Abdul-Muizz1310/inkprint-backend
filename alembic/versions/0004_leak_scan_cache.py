"""7-day leak-scan result cache.

Adds ``leak_scan_cache`` implementing spec 04-leak-scanner.md invariant #3:
results per ``(content_hash, corpus, snapshot)`` are cached so re-scanning the
same text against the same corpus snapshot short-circuits the corpus query.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "leak_scan_cache",
        sa.Column("cache_key", sa.Text(), primary_key=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("corpus", sa.Text(), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("result", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_leak_scan_cache_created_at", "leak_scan_cache", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_leak_scan_cache_created_at", table_name="leak_scan_cache")
    op.drop_table("leak_scan_cache")
