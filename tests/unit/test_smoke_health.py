"""Post-deploy smoke check — ``scripts/smoke_health.py``.

The check has to be *skippable*: the Render service is periodically suspended or
cold, and an unconditional live probe in CI would turn every unrelated pull
request red. So when ``SMOKE_BASE_URL`` is unset the script must exit 0 with a
notice and zero HTTP requests, and it must only fail when a base URL was
supplied and the service genuinely did not come back healthy.

``SMOKE_BASE_URL`` is a bare origin, so the script owns the ``/health`` suffix;
the probed URL is asserted here to carry exactly one separator even when the
configured origin arrives with a trailing slash.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

smoke_health = pytest.importorskip("smoke_health")


def _transport(*responses: httpx.Response, seen: list[str] | None = None) -> httpx.MockTransport:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return httpx.MockTransport(handler)


def _healthy(**overrides: Any) -> httpx.Response:
    body = {"status": "ok", "version": "0.1.0", "db": "ok", "commit_sha": "abc1234"}
    body.update(overrides)
    return httpx.Response(200, json=body)


class TestSkipWhenUnset:
    def test_unset_url_exits_zero(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``None`` falls back to the environment, so the env must be pinned unset.

        Without the ``delenv`` this test would silently start probing a live
        service for anyone who happens to export ``SMOKE_BASE_URL`` in their
        shell — the CI test job leaves it unset, and this keeps the test honest
        regardless.
        """
        monkeypatch.delenv(smoke_health.SMOKE_URL_ENV, raising=False)
        assert smoke_health.main(base_url=None) == 0
        out = capsys.readouterr().out.lower()
        assert "skip" in out
        assert smoke_health.SMOKE_URL_ENV.lower() in out

    def test_blank_url_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert smoke_health.main(base_url="   ") == 0
        assert "skip" in capsys.readouterr().out.lower()

    def test_skipping_never_performs_a_request(self) -> None:
        def explode(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no request may be made when the base URL is unset")

        assert smoke_health.main(base_url="", transport=httpx.MockTransport(explode)) == 0


class TestHealthyService:
    def test_healthy_first_try_exits_zero(self) -> None:
        """The origin is suffixed with ``/health`` by the script, not the caller."""
        seen: list[str] = []
        assert (
            smoke_health.main(
                base_url="https://example.test",
                transport=_transport(_healthy(), seen=seen),
                attempts=3,
                delay=0,
            )
            == 0
        )
        assert seen == ["https://example.test/health"]

    def test_recovers_after_cold_start(self) -> None:
        """A 503 on the first poll is a cold start, not a failure.

        The origin here carries a trailing slash, so this also pins the join to
        exactly one separator — ``//health`` would 404 on a real deploy.
        """
        seen: list[str] = []
        assert (
            smoke_health.main(
                base_url="https://example.test/",
                transport=_transport(httpx.Response(503), _healthy(), seen=seen),
                attempts=4,
                delay=0,
            )
            == 0
        )
        assert seen == ["https://example.test/health"] * 2


class TestUnhealthyService:
    def test_persistent_503_fails(self) -> None:
        assert (
            smoke_health.main(
                base_url="https://example.test",
                transport=_transport(httpx.Response(503)),
                attempts=2,
                delay=0,
            )
            == 1
        )

    def test_db_down_fails_even_with_http_200(self) -> None:
        """``{"status": "ok", "db": "down"}`` is not a healthy deploy."""
        assert (
            smoke_health.main(
                base_url="https://example.test",
                transport=_transport(_healthy(db="down")),
                attempts=2,
                delay=0,
            )
            == 1
        )

    def test_non_ok_status_fails(self) -> None:
        assert (
            smoke_health.main(
                base_url="https://example.test",
                transport=_transport(_healthy(status="degraded")),
                attempts=2,
                delay=0,
            )
            == 1
        )

    def test_non_json_body_fails(self) -> None:
        assert (
            smoke_health.main(
                base_url="https://example.test",
                transport=_transport(httpx.Response(200, text="<html>maintenance</html>")),
                attempts=2,
                delay=0,
            )
            == 1
        )

    def test_connection_error_fails(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        assert (
            smoke_health.main(
                base_url="https://example.test",
                transport=httpx.MockTransport(refuse),
                attempts=2,
                delay=0,
            )
            == 1
        )
