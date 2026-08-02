"""The container entrypoint really applies Alembic migrations.

The README claimed migrations were "auto-applied via Render ``preDeployCommand``"
while no such command existed anywhere — so on Postgres nothing created or
upgraded the schema (``main.lifespan`` restricts auto-create to SQLite). Render
pre-deploy commands additionally require a paid instance type and this service
runs on ``plan: free``, so the migration step has to live in the container.

These tests execute ``docker-entrypoint.sh`` with a stubbed ``uv`` on PATH, so
they assert the branch behaviour rather than merely grepping the file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker-entrypoint.sh"


def _find_posix_shell() -> str | None:
    """Return a shell that can actually run a POSIX script, or ``None``.

    ``shutil.which("bash")`` cannot be trusted on Windows: it resolves to the
    WSL relay stub at ``C:\\Windows\\System32\\bash.exe``, which exits non-zero
    with ``execvpe(/bin/bash) failed`` whenever no WSL distro is installed.
    A stub is indistinguishable from a real shell by path alone, so every
    candidate is probed and only a shell that genuinely executes is returned.
    """
    candidates: list[str | None] = []
    if os.name == "nt":
        # Git for Windows ships a real POSIX shell; prefer it over the WSL stub.
        git = shutil.which("git")
        if git:
            git_root = Path(git).resolve().parent.parent
            candidates += [
                str(git_root / "bin" / "bash.exe"),
                str(git_root / "usr" / "bin" / "sh.exe"),
            ]
    candidates += [shutil.which("sh"), shutil.which("bash")]

    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "echo ok"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "ok":
            return candidate
    return None


_SH = _find_posix_shell()
requires_sh = pytest.mark.skipif(_SH is None, reason="no working POSIX shell available")


def _run_entrypoint(tmp_path: Path, database_url: str | None) -> subprocess.CompletedProcess[str]:
    """Run the entrypoint with a fake ``uv`` that logs its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "uv-calls.log"
    (bin_dir / "uv").write_text(
        f'#!/bin/sh\necho "$@" >> "{log.as_posix()}"\n',
        encoding="utf-8",
    )
    (bin_dir / "uv").chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["PATH"] = f"{bin_dir.as_posix()}{os.pathsep}{env.get('PATH', '')}"
    if database_url is not None:
        env["DATABASE_URL"] = database_url

    assert _SH is not None
    result = subprocess.run(
        [_SH, ENTRYPOINT.as_posix(), "printf", "SERVER_STARTED"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    result.stderr = result.stderr + (
        log.read_text(encoding="utf-8") if log.exists() else "<no uv calls>"
    )
    return result


class TestEntrypointExists:
    def test_entrypoint_script_is_committed(self) -> None:
        assert ENTRYPOINT.is_file()

    def test_dockerfile_uses_the_entrypoint(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "docker-entrypoint.sh" in dockerfile
        assert "ENTRYPOINT" in dockerfile

    def test_dockerfile_does_not_bake_a_placeholder_commit_sha(self) -> None:
        """``ARG COMMIT_SHA=unknown`` is what made /version report "unknown"."""
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "ARG COMMIT_SHA=unknown" not in dockerfile


@requires_sh
class TestEntrypointBehaviour:
    def test_postgres_url_triggers_alembic_upgrade_head(self, tmp_path: Path) -> None:
        result = _run_entrypoint(tmp_path, "postgresql+asyncpg://u:p@host/db")
        assert result.returncode == 0, result.stderr
        assert "alembic upgrade head" in result.stderr
        assert "SERVER_STARTED" in result.stdout

    def test_plain_postgres_scheme_also_triggers_alembic(self, tmp_path: Path) -> None:
        result = _run_entrypoint(tmp_path, "postgres://u:p@host/db")
        assert result.returncode == 0, result.stderr
        assert "alembic upgrade head" in result.stderr

    def test_unset_database_url_skips_alembic_but_still_starts(self, tmp_path: Path) -> None:
        """SQLite has no migration chain — the lifespan auto-creates instead."""
        result = _run_entrypoint(tmp_path, None)
        assert result.returncode == 0, result.stderr
        assert "alembic" not in result.stderr
        assert "SERVER_STARTED" in result.stdout

    def test_sqlite_url_skips_alembic(self, tmp_path: Path) -> None:
        result = _run_entrypoint(tmp_path, "sqlite+aiosqlite:///./inkprint.db")
        assert result.returncode == 0, result.stderr
        assert "alembic" not in result.stderr
        assert "SERVER_STARTED" in result.stdout

    def test_failed_migration_aborts_startup(self, tmp_path: Path) -> None:
        """Never serve traffic against an un-migrated schema."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "uv").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        (bin_dir / "uv").chmod(0o755)

        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        env["PATH"] = f"{bin_dir.as_posix()}{os.pathsep}{env.get('PATH', '')}"
        env["DATABASE_URL"] = "postgresql://u:p@host/db"

        assert _SH is not None
        result = subprocess.run(
            [_SH, ENTRYPOINT.as_posix(), "printf", "SERVER_STARTED"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "SERVER_STARTED" not in result.stdout
