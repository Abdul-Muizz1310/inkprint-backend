"""Persist dossier envelopes for real.

``POST /dossiers/envelope`` signed envelopes into a module-level dict, so every
container restart lost them (frequent on Render's free tier). Moving the store
onto the existing ``dossier_envelopes`` table needs two columns the original
0002 migration omitted:

* ``envelope_metadata`` — part of the idempotency/conflict fingerprint, so it has
  to round-trip or a re-submission of identical inputs would 409 spuriously.
* ``canonical_bundle`` — the exact bytes that were signed. Recomputing them would
  require reproducing ``created_at`` to the microsecond; storing them keeps
  verification exact.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column("dossier_envelopes", sa.Column("envelope_metadata", _JSON, nullable=True))
    op.add_column(
        "dossier_envelopes",
        sa.Column(
            "canonical_bundle", sa.LargeBinary(), nullable=False, server_default=sa.text("''")
        ),
    )
    # The server_default exists only so the NOT NULL column can be added to a
    # table that may already hold rows; new writes always supply the bytes.
    op.alter_column("dossier_envelopes", "canonical_bundle", server_default=None)


def downgrade() -> None:
    op.drop_column("dossier_envelopes", "canonical_bundle")
    op.drop_column("dossier_envelopes", "envelope_metadata")
