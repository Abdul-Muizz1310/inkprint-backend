"""Ops configuration guards — CI workflow, Dependabot, Render blueprint.

These files are only exercised by the platforms that consume them, so a typo
ships silently. Cheap structural assertions here catch the specific regressions
this repo has already had: a CI selector that skipped whole layers, a Dependabot
config that did not exist, and a documented deploy mechanism with no
implementation behind it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
RENDER = REPO_ROOT / "render.yaml"


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestDependabot:
    def test_config_exists_and_parses(self) -> None:
        assert DEPENDABOT.is_file()
        assert isinstance(_load(DEPENDABOT), dict)

    def test_schema_shape(self) -> None:
        config = _load(DEPENDABOT)
        assert config["version"] == 2
        assert isinstance(config["updates"], list) and config["updates"]

    def test_covers_github_actions_and_uv_weekly(self) -> None:
        updates = _load(DEPENDABOT)["updates"]
        ecosystems = {u["package-ecosystem"] for u in updates}
        assert {"github-actions", "uv"} <= ecosystems
        for update in updates:
            assert update["directory"] == "/"
            assert update["schedule"]["interval"] == "weekly"


class TestCiWorkflow:
    def test_parses_and_has_the_expected_jobs(self) -> None:
        jobs = _load(CI)["jobs"]
        assert {"lint", "test", "postgres", "build", "smoke"} <= set(jobs)

    def test_default_test_job_does_not_deselect_integration_tests(self) -> None:
        """They need no Docker and no Postgres; excluding them hid whole modules."""
        run_steps = " ".join(
            step.get("run", "")
            for step in _load(CI)["jobs"]["test"]["steps"]
            if isinstance(step, dict)
        )
        assert "pytest" in run_steps
        assert "not integration" not in run_steps
        assert "--cov=src/inkprint" in run_steps

    def test_postgres_tier_has_its_own_job(self) -> None:
        run_steps = " ".join(
            step.get("run", "")
            for step in _load(CI)["jobs"]["postgres"]["steps"]
            if isinstance(step, dict)
        )
        assert "-m postgres" in run_steps

    def test_smoke_job_is_env_gated_not_hardcoded(self) -> None:
        """The live probe must read a repository variable, never a baked URL."""
        steps = _load(CI)["jobs"]["smoke"]["steps"]
        env_values = [v for step in steps for v in (step.get("env") or {}).values()]
        assert any("vars.INKPRINT_HEALTH_URL" in str(v) for v in env_values)
        run_steps = " ".join(step.get("run", "") for step in steps if isinstance(step, dict))
        assert "scripts/smoke_health.py" in run_steps
        assert "onrender.com" not in run_steps

    def test_build_passes_the_commit_sha_build_arg(self) -> None:
        run_steps = " ".join(
            step.get("run", "")
            for step in _load(CI)["jobs"]["build"]["steps"]
            if isinstance(step, dict)
        )
        assert "--build-arg COMMIT_SHA=" in run_steps


class TestRenderBlueprint:
    def test_parses_and_declares_one_web_service(self) -> None:
        services = _load(RENDER)["services"]
        assert len(services) == 1
        assert services[0]["type"] == "web"
        assert services[0]["healthCheckPath"] == "/health"

    def test_no_predeploycommand_on_a_free_instance(self) -> None:
        """Pre-deploy commands require a paid instance type.

        Declaring one here would be accepted by the Blueprint and silently never
        run — exactly the fiction the README used to document. Migrations run
        from ``docker-entrypoint.sh`` instead.
        """
        service = _load(RENDER)["services"][0]
        if service.get("plan") == "free":
            assert "preDeployCommand" not in service
        entrypoint = (REPO_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
        assert "alembic upgrade head" in entrypoint


class TestProductionDependencyClosure:
    """The production image must be able to boot in its documented default.

    ``Dockerfile`` installs with ``uv sync --frozen --no-dev``, so anything the
    app imports at runtime has to live in ``[project.dependencies]``. The
    zero-config default documented in the README is a local SQLite file
    (``core.db.DEFAULT_DATABASE_URL``), whose driver was declared dev-only —
    the container only booted because ``uv run`` silently re-synced the dev
    group at start-up, and adding ``--no-dev`` made it crash with
    ``ModuleNotFoundError: No module named 'aiosqlite'``.
    """

    @staticmethod
    def _runtime_dependencies() -> list[str]:
        import tomllib

        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps: list[str] = data["project"]["dependencies"]
        return deps

    @staticmethod
    def _dev_dependencies() -> list[str]:
        import tomllib

        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps: list[str] = data["dependency-groups"]["dev"]
        return deps

    def test_default_database_driver_is_a_runtime_dependency(self) -> None:
        from inkprint.core.db import DEFAULT_DATABASE_URL

        assert DEFAULT_DATABASE_URL.startswith("sqlite+aiosqlite")
        runtime = self._runtime_dependencies()
        assert any(d.replace("_", "-").startswith("aiosqlite") for d in runtime), (
            "aiosqlite backs DEFAULT_DATABASE_URL, so `uv sync --no-dev` must install it; "
            f"runtime dependencies are {runtime}"
        )

    def test_driver_is_not_duplicated_into_the_dev_group(self) -> None:
        dev = self._dev_dependencies()
        assert not any(d.replace("_", "-").startswith("aiosqlite") for d in dev)

    def test_container_runtime_commands_use_no_dev(self) -> None:
        """Otherwise every cold start re-syncs the dev group."""
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (REPO_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
        assert '"--no-dev"' in dockerfile
        assert "uv run --no-dev alembic" in entrypoint
