"""ORM/migration type parity guards.

SQLite silently accepts type mismatches that Postgres rejects, so the whole
SQLite-backed suite can be green while production 500s. These are cheap
structural assertions that run in the fast tier; the behavioural proof lives in
``tests/integration/test_postgres_tier.py`` against a real Postgres server.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import DateTime

from inkprint.models import Base

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _datetime_columns() -> list[tuple[str, str, DateTime]]:
    found: list[tuple[str, str, DateTime]] = []
    for table_name, table in Base.metadata.tables.items():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                found.append((table_name, column.name, column.type))
    return found


class TestTimestampsAreTimezoneAware:
    """Every migration declares ``DateTime(timezone=True)``; the ORM must agree.

    A bare ``Mapped[datetime]`` infers ``TIMESTAMP WITHOUT TIME ZONE``. asyncpg
    then refuses the timezone-aware ``datetime.now(UTC)`` the services produce
    ("can't subtract offset-naive and offset-aware datetimes"), so every insert
    fails on Neon while passing on SQLite.
    """

    def test_at_least_one_datetime_column_exists(self) -> None:
        assert _datetime_columns(), "expected the ORM metadata to declare datetime columns"

    @pytest.mark.parametrize(
        ("table", "column", "col_type"),
        [pytest.param(t, c, ty, id=f"{t}.{c}") for t, c, ty in _datetime_columns()],
    )
    def test_datetime_column_is_timezone_aware(
        self, table: str, column: str, col_type: DateTime
    ) -> None:
        assert col_type.timezone is True, (
            f"{table}.{column} maps to TIMESTAMP WITHOUT TIME ZONE while the Alembic "
            "migration declares timezone=True"
        )

    def test_no_migration_declares_a_naive_timestamp(self) -> None:
        """Guard the other direction: a naive column in a migration would also drift."""
        naive = re.compile(r"sa\.DateTime\(\s*\)")
        offenders = [
            path.name
            for path in sorted(MIGRATIONS_DIR.glob("*.py"))
            if naive.search(path.read_text(encoding="utf-8"))
        ]
        assert offenders == []
