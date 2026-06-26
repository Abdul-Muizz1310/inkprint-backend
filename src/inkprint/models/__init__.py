"""SQLAlchemy ORM models for inkprint.

Importing this package registers every mapped class on ``Base.metadata`` so
``Base.metadata.create_all`` (and Alembic autogenerate) see the full schema.
"""

from __future__ import annotations

from inkprint.models.base import Base
from inkprint.models.certificate import Certificate, DerivativeLink
from inkprint.models.envelope import DossierEnvelope
from inkprint.models.leak import LeakScanJob, LeakScanResult

__all__ = [
    "Base",
    "Certificate",
    "DerivativeLink",
    "DossierEnvelope",
    "LeakScanJob",
    "LeakScanResult",
]
