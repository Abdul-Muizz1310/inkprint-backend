"""Where the trusted verification keys come from — spec 09 §1.

bastion's key from ``BASTION_SIGNING_KEY_PUBLIC`` or, when that is empty, from
``BASTION_PUBLIC_KEY_URL`` (cached an hour; a failed fetch is retried after a
minute, never per request); inkprint-frontend's key from
``INKPRINT_FRONTEND_SIGNING_KEY_PUBLIC``. Every value comes from ``Settings`` and
is parsed at this boundary: a value that is not an Ed25519 SPKI key is logged
once by name and treated as absent.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Final

import httpx
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, ValidationError

from inkprint.core.config import Settings
from inkprint.platform.token_verifier import BASTION_ISSUER, FRONTEND_ISSUER, TrustedKey

logger = logging.getLogger(__name__)

BASTION_KEY_ENV: Final = "BASTION_SIGNING_KEY_PUBLIC"
FRONTEND_KEY_ENV: Final = "INKPRINT_FRONTEND_SIGNING_KEY_PUBLIC"
_URL_KEY_TTL_S: Final = 3600.0
_URL_RETRY_AFTER_S: Final = 60.0
_BOM: Final = "﻿"

FetchText = Callable[[str], Awaitable[str]]


class _BastionPublicKey(BaseModel):
    """bastion's ``/api/public-key`` answer; only ``publicKey`` matters here."""

    model_config = ConfigDict(extra="ignore")
    publicKey: str  # noqa: N815 - the wire name


def _clean(value: str) -> str:
    """Strip a byte-order mark and edge whitespace (values pasted from a shell carry them)."""
    return value.strip().lstrip(_BOM).strip()


def parse_ed25519_public_key(value: str) -> Ed25519PublicKey | None:
    """Strict base64 SPKI DER of an Ed25519 key, else ``None``."""
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        der = base64.b64decode(cleaned, validate=True)
        key = serialization.load_der_public_key(der)
    except (binascii.Error, ValueError, UnsupportedAlgorithm):
        return None
    return key if isinstance(key, Ed25519PublicKey) else None


@functools.lru_cache(maxsize=8)
def _parse_named(name: str, value: str) -> Ed25519PublicKey | None:
    """Parse a configured value; cached so a bad one warns once, not per request."""
    key = parse_ed25519_public_key(value)
    if key is None:
        # Name the variable, never its value.
        logger.warning("%s is not a base64 Ed25519 public key (SPKI DER); ignoring it", name)
    return key


_http_client: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    """One process-wide async client, so a key fetch never builds a TLS pool per call."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=5.0)
    return _http_client


async def _fetch_text(url: str) -> str:
    resp = await _client().get(url)
    resp.raise_for_status()
    return resp.text


class TrustedKeySource:
    """Resolves the keys this deployment trusts, in order: bastion, then the frontend."""

    def __init__(
        self,
        *,
        bastion_key: str,
        bastion_key_url: str,
        frontend_key: str,
        fetch_text: FetchText = _fetch_text,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bastion_key = _clean(bastion_key)
        self._bastion_key_url = _clean(bastion_key_url)
        self._frontend_key = _clean(frontend_key)
        self._fetch_text = fetch_text
        self._clock = clock
        # (fetched_at, key or None for a failed fetch)
        self._url_cache: tuple[float, Ed25519PublicKey | None] | None = None
        self._url_lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> TrustedKeySource:
        return cls(
            bastion_key=settings.bastion_signing_key_public,
            bastion_key_url=settings.bastion_public_key_url,
            frontend_key=settings.inkprint_frontend_signing_key_public,
        )

    def is_configured(self) -> bool:
        """True when any key source is set (whether or not it resolves)."""
        return bool(self._bastion_key or self._bastion_key_url or self._frontend_key)

    async def resolve(self) -> tuple[TrustedKey, ...]:
        keys: list[TrustedKey] = []
        bastion = await self._bastion()
        if bastion is not None:
            keys.append(TrustedKey(issuer=BASTION_ISSUER, key=bastion))
        if self._frontend_key:
            frontend = _parse_named(FRONTEND_KEY_ENV, self._frontend_key)
            if frontend is not None:
                keys.append(TrustedKey(issuer=FRONTEND_ISSUER, key=frontend))
        return tuple(keys)

    async def _bastion(self) -> Ed25519PublicKey | None:
        if self._bastion_key:
            return _parse_named(BASTION_KEY_ENV, self._bastion_key)
        if not self._bastion_key_url:
            return None
        async with self._url_lock:
            cached = self._fresh_url_key()
            if cached is not None:
                return cached[1]
            key = await self._fetch_bastion_key(self._bastion_key_url)
            self._url_cache = (self._clock(), key)
            return key

    def _fresh_url_key(self) -> tuple[float, Ed25519PublicKey | None] | None:
        if self._url_cache is None:
            return None
        fetched_at, key = self._url_cache
        ttl = _URL_KEY_TTL_S if key is not None else _URL_RETRY_AFTER_S
        return self._url_cache if self._clock() - fetched_at < ttl else None

    async def _fetch_bastion_key(self, url: str) -> Ed25519PublicKey | None:
        try:
            body = _BastionPublicKey.model_validate_json(await self._fetch_text(url))
        except (httpx.HTTPError, ValidationError) as exc:
            logger.warning(
                "could not fetch bastion public key from %s: %s", url, type(exc).__name__
            )
            return None
        key = parse_ed25519_public_key(body.publicKey)
        if key is None:
            logger.warning("bastion public key from %s is not an Ed25519 SPKI key", url)
        return key
