"""Trusted-key resolution — spec 09 §1 (PT-17, PT-18, PT-24, PT-25)."""

from __future__ import annotations

import base64
import logging

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from inkprint.core.config import Settings
from inkprint.platform.trusted_keys import TrustedKeySource, parse_ed25519_public_key
from tests.platform_keys import keypair

URL = "https://bastion.example.test/api/public-key"
BASTION = keypair()
FRONTEND = keypair()


def _spki_b64(public_key: object) -> str:
    der = public_key.public_bytes(  # type: ignore[attr-defined]
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(der).decode()


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _source(
    *, bastion: str = "", url: str = "", frontend: str = "", clock: _Clock | None = None
) -> TrustedKeySource:
    return TrustedKeySource(
        bastion_key=bastion,
        bastion_key_url=url,
        frontend_key=frontend,
        clock=clock or _Clock(),
    )


def _raw(pub_b64: str) -> bytes:
    return base64.b64decode(pub_b64)


def _key_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


# ── Parsing ──────────────────────────────────────────────────────────────────


class TestParse:
    def test_parses_spki_der_base64(self) -> None:
        key = parse_ed25519_public_key(BASTION.public_b64)
        assert isinstance(key, Ed25519PublicKey)
        assert _key_bytes(key) == _raw(BASTION.public_b64)

    @pytest.mark.parametrize("wrap", ["﻿{}", "{}\r\n", "  {}\n", "﻿ {} \r\n"])
    def test_pt18_strips_bom_and_edge_whitespace(self, wrap: str) -> None:
        assert parse_ed25519_public_key(wrap.format(BASTION.public_b64)) is not None

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "﻿",
            "not base64!",
            BASTION.public_b64[:-4],  # truncated
            BASTION.public_b64[:20] + "\n" + BASTION.public_b64[20:],  # inner line break
            base64.b64encode(b"junk bytes that are not a key").decode(),
            _spki_b64(rsa.generate_private_key(public_exponent=65537, key_size=1024).public_key()),
            _spki_b64(X25519PrivateKey.generate().public_key()),
        ],
    )
    def test_pt24_rejects_anything_but_an_ed25519_spki_key(self, value: str) -> None:
        assert parse_ed25519_public_key(value) is None


# ── Configured-ness ──────────────────────────────────────────────────────────


class TestIsConfigured:
    def test_nothing_set(self) -> None:
        assert _source().is_configured() is False

    def test_only_invisible_bytes_count_as_unset(self) -> None:
        assert _source(bastion="﻿ \r\n", url="  ", frontend="\n").is_configured() is False

    @pytest.mark.parametrize("field", ["bastion", "url", "frontend"])
    def test_any_single_source(self, field: str) -> None:
        assert _source(**{field: "x"}).is_configured() is True


# ── Resolution ───────────────────────────────────────────────────────────────


class TestResolve:
    @respx.mock(assert_all_called=False)
    async def test_env_key_wins_over_the_url_without_a_fetch(
        self, respx_mock: respx.Router
    ) -> None:
        route = respx_mock.get(URL)
        keys = await _source(bastion=BASTION.public_b64, url=URL).resolve()
        assert [k.issuer for k in keys] == ["bastion"]
        assert _key_bytes(keys[0].key) == _raw(BASTION.public_b64)
        assert route.called is False

    async def test_frontend_only(self) -> None:
        keys = await _source(frontend=FRONTEND.public_b64).resolve()
        assert [k.issuer for k in keys] == ["inkprint-frontend"]

    async def test_bastion_first_then_frontend(self) -> None:
        keys = await _source(bastion=BASTION.public_b64, frontend=FRONTEND.public_b64).resolve()
        assert [k.issuer for k in keys] == ["bastion", "inkprint-frontend"]

    async def test_nothing_configured_resolves_nothing(self) -> None:
        assert await _source().resolve() == ()

    @respx.mock
    async def test_pt17_url_key_is_fetched_once_and_cached(self, respx_mock: respx.Router) -> None:
        route = respx_mock.get(URL).mock(
            return_value=httpx.Response(200, json={"kid": "k", "publicKey": BASTION.public_b64})
        )
        clock = _Clock()
        source = _source(url=URL, clock=clock)
        first = await source.resolve()
        clock.now += 3599
        second = await source.resolve()
        assert [k.issuer for k in first] == [k.issuer for k in second] == ["bastion"]
        assert route.call_count == 1

    @respx.mock
    async def test_url_key_is_refetched_after_an_hour(self, respx_mock: respx.Router) -> None:
        route = respx_mock.get(URL).mock(
            return_value=httpx.Response(200, json={"publicKey": BASTION.public_b64})
        )
        clock = _Clock()
        source = _source(url=URL, clock=clock)
        await source.resolve()
        clock.now += 3601
        await source.resolve()
        assert route.call_count == 2

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(500),
            httpx.Response(404, json={"publicKey": "x"}),
            httpx.Response(200, json={"kid": "k"}),
            httpx.Response(200, json={"publicKey": 42}),
            httpx.Response(200, json={"publicKey": "not base64!"}),
            httpx.Response(200, text="<html>not json</html>"),
            httpx.Response(200, json=["publicKey"]),
        ],
    )
    @respx.mock
    async def test_pt25_failed_fetch_means_no_bastion_key_and_a_warning(
        self,
        respx_mock: respx.Router,
        response: httpx.Response,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        respx_mock.get(URL).mock(return_value=response)
        caplog.set_level(logging.WARNING, logger="inkprint.platform.trusted_keys")
        keys = await _source(url=URL, frontend=FRONTEND.public_b64).resolve()
        assert [k.issuer for k in keys] == ["inkprint-frontend"]
        assert any("bastion public key" in r.getMessage() for r in caplog.records)

    @respx.mock
    async def test_pt25_network_error_is_a_failed_fetch(self, respx_mock: respx.Router) -> None:
        respx_mock.get(URL).mock(side_effect=httpx.ConnectError("down"))
        assert await _source(url=URL).resolve() == ()

    @respx.mock
    async def test_pt25_failure_is_not_retried_within_a_minute(
        self, respx_mock: respx.Router
    ) -> None:
        route = respx_mock.get(URL).mock(return_value=httpx.Response(503))
        clock = _Clock()
        source = _source(url=URL, clock=clock)
        await source.resolve()
        clock.now += 59
        await source.resolve()
        assert route.call_count == 1
        clock.now += 2
        route.mock(return_value=httpx.Response(200, json={"publicKey": BASTION.public_b64}))
        keys = await source.resolve()
        assert route.call_count == 2
        assert [k.issuer for k in keys] == ["bastion"]

    async def test_pt24_malformed_env_key_warns_once_by_name_never_value(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        secretish = "not-a-key-but-looks-private-0123456789"
        caplog.set_level(logging.WARNING, logger="inkprint.platform.trusted_keys")
        source = _source(bastion=secretish, frontend="also bad")
        assert await source.resolve() == ()
        assert await source.resolve() == ()
        messages = [r.getMessage() for r in caplog.records]
        assert sum("BASTION_SIGNING_KEY_PUBLIC" in m for m in messages) == 1
        assert sum("INKPRINT_FRONTEND_SIGNING_KEY_PUBLIC" in m for m in messages) == 1
        assert not any(secretish in m or "also bad" in m for m in messages)


# ── Settings, not os.environ ─────────────────────────────────────────────────


class TestFromSettings:
    @respx.mock
    async def test_pt17_reads_the_url_from_settings_not_the_environment(
        self, respx_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BASTION_PUBLIC_KEY_URL", "https://wrong.example.test/key")
        monkeypatch.setenv("BASTION_SIGNING_KEY_PUBLIC", "")
        route = respx_mock.get(URL).mock(
            return_value=httpx.Response(200, json={"publicKey": BASTION.public_b64})
        )
        settings = Settings(
            _env_file=None,
            bastion_signing_key_public="",
            bastion_public_key_url=URL,
            inkprint_frontend_signing_key_public=FRONTEND.public_b64,
        )
        keys = await TrustedKeySource.from_settings(settings).resolve()
        assert route.call_count == 1
        assert [k.issuer for k in keys] == ["bastion", "inkprint-frontend"]

    def test_pt20_settings_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "DEMO_MODE",
            "BASTION_SIGNING_KEY_PUBLIC",
            "BASTION_PUBLIC_KEY_URL",
            "INKPRINT_FRONTEND_SIGNING_KEY_PUBLIC",
        ):
            monkeypatch.delenv(var, raising=False)
        settings = Settings(_env_file=None)
        assert settings.demo_mode is False
        assert settings.bastion_signing_key_public == ""
        assert settings.inkprint_frontend_signing_key_public == ""
        assert settings.bastion_public_key_url.startswith("https://")
