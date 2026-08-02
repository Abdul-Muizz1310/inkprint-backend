"""Post-deploy smoke check — ``scripts/smoke_health.py``.

The check has to be *skippable*: the Render service is periodically suspended or
cold, and an unconditional live probe in CI would turn every unrelated pull
request red. So when the URL variable is unset the script must exit 0 with a
notice, and it must only fail when a URL was supplied and the service genuinely
did not come back healthy.
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


def _transport(*responses: httpx.Response) -> httpx.MockTransport:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return httpx.MockTransport(handler)


def _healthy(**overrides: Any) -> httpx.Response:
    body = {"status": "ok", "version": "0.1.0", "db": "ok", "commit_sha": "abc1234"}
    body.update(overrides)
    return httpx.Response(200, json=body)


class TestSkipWhenUnset:
    def test_unset_url_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert smoke_health.main(url=None) == 0
        assert "skip" in capsys.readouterr().out.lower()

    def test_blank_url_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert smoke_health.main(url="   ") == 0
        assert "skip" in capsys.readouterr().out.lower()

    def test_skipping_never_performs_a_request(self) -> None:
        def explode(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no request may be made when the URL is unset")

        assert smoke_health.main(url="", transport=httpx.MockTransport(explode)) == 0


class TestHealthyService:
    def test_healthy_first_try_exits_zero(self) -> None:
        assert (
            smoke_health.main(
                url="https://example.test/health",
                transport=_transport(_healthy()),
                attempts=3,
                delay=0,
            )
            == 0
        )

    def test_recovers_after_cold_start(self) -> None:
        """A 503 on the first poll is a cold start, not a failure."""
        assert (
            smoke_health.main(
                url="https://example.test/health",
                transport=_transport(httpx.Response(503), _healthy()),
                attempts=4,
                delay=0,
            )
            == 0
        )


class TestUnhealthyService:
    def test_persistent_503_fails(self) -> None:
        assert (
            smoke_health.main(
                url="https://example.test/health",
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
                url="https://example.test/health",
                transport=_transport(_healthy(db="down")),
                attempts=2,
                delay=0,
            )
            == 1
        )

    def test_non_ok_status_fails(self) -> None:
        assert (
            smoke_health.main(
                url="https://example.test/health",
                transport=_transport(_healthy(status="degraded")),
                attempts=2,
                delay=0,
            )
            == 1
        )

    def test_non_json_body_fails(self) -> None:
        assert (
            smoke_health.main(
                url="https://example.test/health",
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
                url="https://example.test/health",
                transport=httpx.MockTransport(refuse),
                attempts=2,
                delay=0,
            )
            == 1
        )
