"""Build-provenance reporting for /health and /version.

The deployed service reported ``commit_sha: "unknown"`` while HEAD was a real
commit, because ``Dockerfile`` sets ``ARG COMMIT_SHA=unknown`` and nothing ever
passes a build arg. Render does not support build args in a Blueprint, but it
*does* inject ``RENDER_GIT_COMMIT`` into every service at runtime — so the
resolver has to consider it, and must treat placeholder values as "absent"
rather than reporting them as if they were a commit.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from inkprint.platform.health import resolve_commit_sha

_KEYS = ("COMMIT_SHA", "RENDER_GIT_COMMIT")


def _env(**overrides: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _KEYS}
    env.update(overrides)
    return env


class TestResolveCommitSha:
    def test_explicit_commit_sha_wins(self) -> None:
        with patch.dict(
            os.environ, _env(COMMIT_SHA="abc1234", RENDER_GIT_COMMIT="def5678"), clear=True
        ):
            assert resolve_commit_sha() == "abc1234"

    def test_falls_back_to_render_git_commit(self) -> None:
        with patch.dict(os.environ, _env(RENDER_GIT_COMMIT="def5678"), clear=True):
            assert resolve_commit_sha() == "def5678"

    @pytest.mark.parametrize("placeholder", ["", "unknown", "UNKNOWN", "  ", "none"])
    def test_placeholder_commit_sha_is_treated_as_absent(self, placeholder: str) -> None:
        """The Dockerfile's default must not be reported as a commit."""
        with patch.dict(
            os.environ,
            _env(COMMIT_SHA=placeholder, RENDER_GIT_COMMIT="def5678"),
            clear=True,
        ):
            assert resolve_commit_sha() == "def5678"

    def test_dev_when_nothing_is_set(self) -> None:
        with patch.dict(os.environ, _env(), clear=True):
            assert resolve_commit_sha() == "dev"

    def test_placeholders_everywhere_still_yields_dev(self) -> None:
        with patch.dict(
            os.environ,
            _env(COMMIT_SHA="unknown", RENDER_GIT_COMMIT=""),
            clear=True,
        ):
            assert resolve_commit_sha() == "dev"


class TestEndpointsUseTheResolver:
    async def test_health_and_version_agree(self) -> None:
        from httpx import ASGITransport, AsyncClient

        from inkprint.main import app

        with patch.dict(os.environ, _env(RENDER_GIT_COMMIT="cafebabe"), clear=True):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                health = await client.get("/health")
                version = await client.get("/version")

        assert health.json()["commit_sha"] == "cafebabe"
        assert version.json()["commit_sha"] == "cafebabe"
