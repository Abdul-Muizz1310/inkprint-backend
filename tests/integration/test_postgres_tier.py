"""Real-Postgres integration tier — Testcontainers, not SQLite.

Everything else in ``tests/`` runs against in-memory SQLite (``tests/conftest.py``
binds it for every test), which is fast but cannot catch the class of bug that
only exists on Postgres: JSONB/UUID[]/BYTEA column behaviour, ``CREATE EXTENSION
vector``, server-side defaults, and whether the Alembic chain actually applies.
Production is Neon Postgres, so this tier exercises the same code against a real
Postgres server.

Marked ``postgres`` (not merely ``integration``) because it is the only tier that
genuinely needs Docker. It self-skips when Docker or the image is unavailable, so
a laptop without Docker still gets a green suite; CI runs it as its own job.

The container image is ``pgvector/pgvector:pg17`` rather than plain ``postgres``
because migration 0001 opens with ``CREATE EXTENSION IF NOT EXISTS vector``.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from inkprint.core import db

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

PG_IMAGE = "pgvector/pgvector:pg17"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    """Start a Postgres container for the session; skip when Docker is absent."""
    postgres_mod = pytest.importorskip(
        "testcontainers.postgres",
        reason="testcontainers[postgres] not installed",
    )
    try:
        container = postgres_mod.PostgresContainer(PG_IMAGE, driver=None)
        container.start()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Docker/Testcontainers unavailable ({type(exc).__name__}: {exc})")

    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
def migrated_pg_dsn(pg_dsn: str) -> str:
    """Apply the whole Alembic chain to the container and return the async DSN.

    Running the migrations (rather than ``Base.metadata.create_all``) is the point:
    the deployed schema is produced by Alembic, so this is what must be verified.

    The DSN handed to Alembic uses ``+asyncpg`` deliberately. ``asyncpg`` is the
    only Postgres driver in ``[project.dependencies]``, so it is the only one
    present in the production image; a migration step that silently needs
    ``psycopg2`` cannot run on deploy. Passing the async DSN here reproduces the
    production environment exactly.
    """
    async_dsn = pg_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    assert async_dsn.startswith("postgresql+asyncpg://"), async_dsn
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**_clean_env(), "DATABASE_URL": async_dsn},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}"
    return async_dsn


def _clean_env() -> dict[str, str]:
    import os

    # Keep PATH etc., but never let a developer's own DATABASE_URL leak in.
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    return env


@pytest.fixture()
async def pg_engine(migrated_pg_dsn: str) -> Any:
    """Point the application's global engine at the migrated Postgres database.

    Depends (transitively, via ordering) on the autouse SQLite ``db_tables``
    fixture having already run, so this rebinding wins for the duration of the
    test. Each test truncates the tables it touches to stay independent.
    """
    engine = create_async_engine(migrated_pg_dsn, poolclass=None)
    db.configure_engine(engine)
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE certificates, derivative_links, dossier_envelopes CASCADE")
        )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture()
async def pg_client(pg_engine: Any) -> Any:
    from inkprint.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestAlembicOnRealPostgres:
    async def test_migration_chain_reaches_head(self, pg_engine: Any) -> None:
        """The Alembic chain applies cleanly and stamps the newest revision."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        expected_head = ScriptDirectory.from_config(cfg).get_current_head()

        async with pg_engine.connect() as conn:
            applied = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        assert applied == expected_head

    async def test_every_orm_table_exists_in_the_migrated_schema(self, pg_engine: Any) -> None:
        """No ORM model may rely on SQLite auto-create to exist in production.

        ``main.lifespan`` only auto-creates on SQLite, so a table that exists in
        the ORM metadata but not in the Alembic chain would 500 on Neon.
        """
        from inkprint.models import Base

        async with pg_engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
            )
            present = {r[0] for r in rows}
        assert set(Base.metadata.tables) <= present, set(Base.metadata.tables) - present

    async def test_pgvector_extension_is_installed(self, pg_engine: Any) -> None:
        """Migration 0001 declares the vector extension; prove it landed."""
        async with pg_engine.connect() as conn:
            installed = (
                await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            ).scalar()
        assert installed == 1


class TestCertificateFlowOnRealPostgres:
    async def test_certificate_round_trips_through_postgres(self, pg_client: Any) -> None:
        created = await pg_client.post(
            "/certificates",
            json={"text": "postgres round trip", "author": "pg@example.com"},
        )
        assert created.status_code == 201, created.text
        cert_id = created.json()["id"]

        fetched = await pg_client.get(f"/certificates/{cert_id}")
        assert fetched.status_code == 200
        assert fetched.json()["content_hash"] == created.json()["content_hash"]

    async def test_exact_search_finds_the_certificate_on_postgres(self, pg_client: Any) -> None:
        await pg_client.post(
            "/certificates",
            json={"text": "searchable on postgres", "author": "pg@example.com"},
        )
        found = await pg_client.get(
            "/search", params={"text": "searchable on postgres", "mode": "exact"}
        )
        assert found.status_code == 200
        assert found.json()["total"] == 1

    async def test_whitespace_only_text_is_rejected_on_postgres_too(self, pg_client: Any) -> None:
        """The canonical-bytes guard is engine-independent (spec 05 TC-A-31)."""
        resp = await pg_client.post("/certificates", json={"text": "   ", "author": "a@b.c"})
        assert resp.status_code == 422


class TestEnvelopePersistenceOnRealPostgres:
    async def test_envelope_survives_in_jsonb_and_bytea_columns(self, pg_client: Any) -> None:
        """The envelope row uses JSONB, UUID[] and BYTEA — none exercised by SQLite.

        SQLite maps all three to JSON/BLOB variants, so this is the only place the
        production column types are actually written and read.
        """
        from inkprint.services import envelope_service

        evidence: list[str] = []
        for i in range(2):
            resp = await pg_client.post(
                "/certificates",
                json={"text": f"evidence {i}", "author": "pg@example.com"},
            )
            assert resp.status_code == 201
            evidence.append(resp.json()["id"])

        dossier_id = str(uuid4())
        created = await pg_client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": dossier_id,
                "evidence_cert_ids": evidence,
                "debate_transcript_hash": "a" * 64,
                "perf_receipt_hash": "b" * 64,
                "metadata": {"engine": "postgres"},
            },
        )
        assert created.status_code == 200, created.text

        reloaded = await envelope_service.get_envelope(dossier_id)
        assert reloaded is not None
        assert reloaded["envelope_id"] == UUID(dossier_id)
        assert isinstance(reloaded["canonical_bundle"], bytes)
        assert reloaded["metadata"] == {"engine": "postgres"}
        assert [str(c) for c in reloaded["evidence_cert_ids"]] == evidence

    async def test_duplicate_dossier_with_different_bundle_conflicts_on_postgres(
        self, pg_client: Any
    ) -> None:
        """Idempotency/conflict detection reads the fingerprint back out of Postgres."""
        resp = await pg_client.post(
            "/certificates",
            json={"text": "conflict evidence", "author": "pg@example.com"},
        )
        evidence = [resp.json()["id"]]
        dossier_id = str(uuid4())
        body: dict[str, Any] = {
            "dossier_id": dossier_id,
            "evidence_cert_ids": evidence,
            "debate_transcript_hash": "a" * 64,
            "perf_receipt_hash": "b" * 64,
            "metadata": {"round": "1"},
        }
        first = await pg_client.post("/dossiers/envelope", json=body)
        assert first.status_code == 200

        same_again = await pg_client.post("/dossiers/envelope", json=body)
        assert same_again.status_code == 200
        assert same_again.json()["envelope_signature"] == first.json()["envelope_signature"]

        different = await pg_client.post(
            "/dossiers/envelope", json={**body, "metadata": {"round": "2"}}
        )
        assert different.status_code == 409


class TestAlembicNeedsOnlyAsyncpg:
    """`alembic upgrade head` must run with the production dependency set.

    Regression guard: ``alembic/env.py`` used to strip ``+asyncpg`` from
    ``DATABASE_URL`` to obtain a "sync driver", which makes SQLAlchemy import
    ``psycopg2`` — not a project dependency, absent from the image. The deploy's
    migration step therefore died with ``ModuleNotFoundError: psycopg2`` before
    applying anything.
    """

    def test_no_sync_postgres_driver_is_a_project_dependency(self) -> None:
        import tomllib

        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = " ".join(data["project"]["dependencies"]).lower()
        assert "psycopg" not in declared
        assert "asyncpg" in declared

    def test_upgrade_head_succeeds_with_psycopg2_import_blocked(
        self, migrated_pg_dsn: str, tmp_path: Path
    ) -> None:
        """Run the migration chain again with psycopg2 made unimportable.

        Idempotent: the database is already at head, so this re-runs the same
        code path Render executes on a no-op deploy.
        """
        blocker = tmp_path / "sitecustomize.py"
        blocker.write_text(
            "import sys\n"
            "class _Block:\n"
            "    def find_module(self, name, path=None):\n"
            "        return self if name.split('.')[0] in ('psycopg2', 'psycopg') else None\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in ('psycopg2', 'psycopg'):\n"
            "            raise ImportError('blocked for test: ' + name)\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n",
            encoding="utf-8",
        )
        env = {
            **_clean_env(),
            "DATABASE_URL": migrated_pg_dsn,
            "PYTHONPATH": str(tmp_path),
        }
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"alembic could not run without psycopg2:\n{result.stdout}\n{result.stderr}"
        )
        assert "psycopg2" not in result.stderr
