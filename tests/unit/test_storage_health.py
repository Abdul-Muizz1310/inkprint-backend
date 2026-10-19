"""Storage health — spec 08 (R2 archival outcome on /health, WARNING on failure)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from httpx import ASGITransport, AsyncClient

from inkprint.core import r2, storage_health
from inkprint.core.config import Settings
from inkprint.main import app

_SECRET = "s3cr3t-access-key-value"
_MESSAGE_ONLY = "message-only-detail-never-logged"


def _configured() -> Settings:
    return Settings(
        r2_endpoint="https://r2.example.test",
        r2_access_key_id="AKIAEXAMPLE",
        r2_secret_access_key=_SECRET,
        r2_bucket="muizz-lab",
    )


def _unconfigured() -> Settings:
    return Settings(r2_endpoint="", r2_access_key_id="", r2_secret_access_key="")


def _client_error(code: str = "Unauthorized", operation: str = "PutObject") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": _MESSAGE_ONLY}}, operation)


@pytest.fixture(autouse=True)
def _fresh_outcome() -> Iterator[None]:
    storage_health.reset()
    yield
    storage_health.reset()


@pytest.fixture()
def configured() -> Iterator[None]:
    with patch("inkprint.core.r2.get_settings", return_value=_configured()):
        yield


@pytest.fixture()
def unconfigured() -> Iterator[None]:
    with patch("inkprint.core.r2.get_settings", return_value=_unconfigured()):
        yield


@pytest.fixture()
async def client() -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _fake_s3(**methods: Any) -> MagicMock:
    s3 = MagicMock(name="s3")
    for name, behaviour in methods.items():
        getattr(s3, name).side_effect = behaviour
    return s3


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING]


# ── The pure status table ─────────────────────────────────────────────────────


class TestStatusTable:
    @pytest.mark.parametrize(
        ("configured", "last_ok", "expected"),
        [
            (False, None, "degraded"),  # SH-1
            (False, True, "degraded"),
            (False, False, "degraded"),
            (True, None, "ok"),  # SH-2
            (True, True, "ok"),  # SH-3
            (True, False, "degraded"),  # SH-4
        ],
    )
    def test_status_table(self, configured: bool, last_ok: bool | None, expected: str) -> None:
        assert storage_health.storage_status(configured=configured, last_ok=last_ok) == expected

    def test_sh5_recovers_after_success_and_degrades_after_failure(self) -> None:
        storage_health.record_failure()
        storage_health.record_success()
        assert storage_health.last_ok() is True
        storage_health.record_failure()
        assert storage_health.last_ok() is False

    def test_reset_forgets_the_outcome(self) -> None:
        storage_health.record_failure()
        storage_health.reset()
        assert storage_health.last_ok() is None


# ── /health ───────────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    async def test_sh1_unconfigured_is_degraded(
        self, client: AsyncClient, unconfigured: None
    ) -> None:
        body = (await client.get("/health")).json()
        assert body["status"] == "ok"
        assert body["storage"] == "degraded"

    async def test_sh2_configured_without_an_operation_is_ok(
        self, client: AsyncClient, configured: None
    ) -> None:
        assert (await client.get("/health")).json()["storage"] == "ok"

    async def test_sh4_configured_after_a_failure_is_degraded(
        self, client: AsyncClient, configured: None
    ) -> None:
        storage_health.record_failure()
        assert (await client.get("/health")).json()["storage"] == "degraded"

    async def test_sh6_health_never_builds_an_s3_client(
        self, client: AsyncClient, configured: None
    ) -> None:
        boom = AssertionError("/health must not touch R2")
        with (
            patch("inkprint.core.r2._get_client", side_effect=boom),
            patch("inkprint.core.r2.boto3.client", side_effect=boom),
        ):
            for _ in range(20):
                resp = await client.get("/health")
                assert resp.status_code == 200
                assert resp.json()["storage"] in {"ok", "degraded"}


# ── Recording and logging on each operation ───────────────────────────────────


class TestUploadOutcome:
    async def test_success_records_ok(self, configured: None) -> None:
        s3 = _fake_s3(put_object=lambda **_: {})
        with patch("inkprint.core.r2.boto3.client", return_value=s3):
            key = await r2.archive_text("certificates/a.json", "hello")
        assert key == "inkprint/certificates/a.json"
        assert storage_health.last_ok() is True
        assert r2.storage_status() == "ok"

    async def test_sh10_client_error_warns_with_operation_key_class_and_code(
        self, configured: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        s3 = _fake_s3(put_object=_client_error("Unauthorized"))
        caplog.set_level(logging.DEBUG, logger="inkprint.core.r2")
        with patch("inkprint.core.r2.boto3.client", return_value=s3):
            assert await r2.archive_text("certificates/b.json", "hello") is None

        warnings = _warnings(caplog)
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "put_object" in message
        assert "inkprint/certificates/b.json" in message
        assert "ClientError" in message
        assert "Unauthorized" in message
        assert _MESSAGE_ONLY not in message
        assert _SECRET not in message
        assert warnings[0].exc_info is None
        assert r2.storage_status() == "degraded"

    @pytest.mark.parametrize(
        "error",
        [EndpointConnectionError(endpoint_url="https://r2.example.test"), OSError("socket")],
    )
    async def test_sh11_non_client_error_warns_with_its_class(
        self, configured: None, caplog: pytest.LogCaptureFixture, error: Exception
    ) -> None:
        s3 = _fake_s3(put_object=error)
        with patch("inkprint.core.r2.boto3.client", return_value=s3):
            assert await r2.archive_text("certificates/c.json", "hello") is None
        warnings = _warnings(caplog)
        assert len(warnings) == 1
        assert type(error).__name__ in warnings[0].getMessage()
        assert r2.storage_status() == "degraded"

    async def test_sh5_a_later_success_recovers(self, configured: None) -> None:
        failing = _fake_s3(put_object=_client_error())
        working = _fake_s3(put_object=lambda **_: {})
        with patch("inkprint.core.r2.boto3.client", return_value=failing):
            await r2.archive_text("certificates/d.json", "x")
        assert r2.storage_status() == "degraded"
        with patch("inkprint.core.r2.boto3.client", return_value=working):
            await r2.archive_text("certificates/d.json", "x")
        assert r2.storage_status() == "ok"

    async def test_sh14_unconfigured_archive_is_silent_and_records_nothing(
        self, unconfigured: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch("inkprint.core.r2.boto3.client", side_effect=AssertionError("no client")):
            assert await r2.archive_text("certificates/e.json", "x") is None
        assert _warnings(caplog) == []
        assert storage_health.last_ok() is None


class TestDownloadOutcome:
    def test_success_records_ok(self, configured: None) -> None:
        body = MagicMock()
        body.read.return_value = b"text"
        s3 = _fake_s3(get_object=lambda **_: {"Body": body})
        with patch("inkprint.core.r2.boto3.client", return_value=s3):
            assert r2.download_text("inkprint/certificates/f.json") == "text"
        assert storage_health.last_ok() is True

    def test_sh12_failure_warns_records_and_reraises(
        self, configured: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        s3 = _fake_s3(get_object=_client_error("NoSuchKey", "GetObject"))
        with (
            patch("inkprint.core.r2.boto3.client", return_value=s3),
            pytest.raises(ClientError),
        ):
            r2.download_text("inkprint/certificates/g.json")
        warnings = _warnings(caplog)
        assert len(warnings) == 1
        assert "get_object" in warnings[0].getMessage()
        assert "NoSuchKey" in warnings[0].getMessage()
        assert storage_health.last_ok() is False


# ── Startup probe ─────────────────────────────────────────────────────────────


class TestStartupProbe:
    def test_sh7_configured_probe_lists_one_key_under_the_prefix(self, configured: None) -> None:
        s3 = _fake_s3(list_objects_v2=lambda **_: {"KeyCount": 0})
        with patch("inkprint.core.r2.boto3.client", return_value=s3):
            r2.probe_storage()
        s3.list_objects_v2.assert_called_once_with(
            Bucket="muizz-lab", Prefix="inkprint/", MaxKeys=1
        )
        assert r2.storage_status() == "ok"

    def test_sh8_unconfigured_probe_builds_no_client_and_warns_once(
        self, unconfigured: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch("inkprint.core.r2.boto3.client", side_effect=AssertionError("no client")):
            r2.probe_storage()
        warnings = _warnings(caplog)
        assert len(warnings) == 1
        assert "disabled" in warnings[0].getMessage()
        assert r2.storage_status() == "degraded"

    def test_sh13_failing_probe_warns_degrades_and_does_not_raise(
        self, configured: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        s3 = _fake_s3(list_objects_v2=_client_error("Unauthorized", "ListObjectsV2"))
        with patch("inkprint.core.r2.boto3.client", return_value=s3):
            r2.probe_storage()  # must not raise
        warnings = _warnings(caplog)
        assert len(warnings) == 1
        assert "list_objects_v2" in warnings[0].getMessage()
        assert "Unauthorized" in warnings[0].getMessage()
        assert r2.storage_status() == "degraded"

    def test_client_uses_short_timeouts_and_one_attempt(self, configured: None) -> None:
        with patch("inkprint.core.r2.boto3.client") as factory:
            r2._get_client()
        config = factory.call_args.kwargs["config"]
        assert config.connect_timeout == 3
        assert config.read_timeout == 5
        assert config.retries == {"total_max_attempts": 1}

    async def test_lifespan_schedules_the_probe_without_awaiting_it(self) -> None:
        from inkprint.main import lifespan

        with patch("inkprint.core.r2.probe_storage") as probe:
            async with lifespan(app):
                task = app.state.storage_probe
            await task
        probe.assert_called_once_with()


# ── Composed: a failing archive degrades /health but not the certificate ─────


class TestComposedFlow:
    async def test_sh9_failed_archive_still_issues_and_degrades_health(
        self, client: AsyncClient, configured: None
    ) -> None:
        s3 = _fake_s3(put_object=_client_error("Unauthorized"))
        with patch("inkprint.core.r2.boto3.client", return_value=s3):
            resp = await client.post(
                "/certificates", json={"text": "Archived or not.", "author": "a@b.com"}
            )
        assert resp.status_code == 201
        cert_id = UUID(resp.json()["id"])
        assert resp.json()["storage_key"] == f"certificates/{cert_id}.json"
        assert (await client.get("/health")).json()["storage"] == "degraded"
