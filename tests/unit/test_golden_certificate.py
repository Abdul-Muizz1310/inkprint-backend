"""Certificates already issued keep verifying — spec 01-signing, TC-S-14..TC-S-18.

Every other signer test generates a fresh keypair, so a ``cryptography`` upgrade
that changed key loading, encoding or verification would pass them while every
stored certificate stopped verifying. ``tests/fixtures/golden_certificate.json``
freezes one certificate issued before the 2026-11 dependency pass. Never
regenerate it to make these tests pass: a failure here is the regression.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from httpx import ASGITransport, AsyncClient

from inkprint.core.keys import derive_key_id, load_signing_keys
from inkprint.main import app
from inkprint.provenance.canonicalize import canonicalize
from inkprint.provenance.manifest import validate_manifest
from inkprint.provenance.signer import sign
from inkprint.services.certificate_service import verify_certificate

FIXTURE = Path(__file__).parent.parent / "fixtures" / "golden_certificate.json"


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def golden_public_key(golden: dict[str, Any]) -> Ed25519PublicKey:
    key = load_pem_public_key(golden["public_key_pem"].encode("ascii"))
    assert isinstance(key, Ed25519PublicKey)
    return key


@pytest.fixture()
def golden_env(golden: dict[str, Any]) -> Iterator[None]:
    env = {**golden["env"], "INKPRINT_KEY_ID": ""}
    with patch.dict(os.environ, env):
        yield


def test_tc_s_14_env_keys_load_and_derive_the_recorded_key_id(
    golden: dict[str, Any], golden_env: None
) -> None:
    _, public_key, key_id = load_signing_keys()
    assert key_id == golden["key_id"] == golden["manifest"]["signature"]["key_id"]
    assert derive_key_id(public_key) == golden["key_id"]


def test_tc_s_15_recorded_certificate_verifies(
    golden: dict[str, Any], golden_public_key: Ed25519PublicKey
) -> None:
    result = verify_certificate(golden["manifest"], golden["text"], public_key=golden_public_key)
    assert result == {"valid": True, "checks": {"signature": True, "hash": True}, "warnings": []}


@pytest.fixture()
async def client_with_golden_key(golden_public_key: Ed25519PublicKey) -> AsyncIterator[AsyncClient]:
    original = app.state.public_key
    app.state.public_key = golden_public_key
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.state.public_key = original


async def test_tc_s_16_post_verify_accepts_the_recorded_certificate(
    golden: dict[str, Any], client_with_golden_key: AsyncClient
) -> None:
    resp = await client_with_golden_key.post(
        "/verify", json={"manifest": golden["manifest"], "text": golden["text"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["checks"] == {"signature": True, "hash": True}


def test_tc_s_17_resigning_reproduces_the_recorded_signature(
    golden: dict[str, Any], golden_env: None
) -> None:
    private_key, _, _ = load_signing_keys()
    signature = sign(canonicalize(golden["text"]), private_key)
    assert signature == golden["signature"] == golden["manifest"]["signature"]["value"]
    assert len(base64.b64decode(signature)) == 64


def test_tc_s_18_schema_still_accepts_it_and_one_changed_character_fails(
    golden: dict[str, Any], golden_public_key: Ed25519PublicKey
) -> None:
    validate_manifest(golden["manifest"])
    tampered = golden["text"].replace("notes", "nodes")
    assert tampered != golden["text"]
    result = verify_certificate(golden["manifest"], tampered, public_key=golden_public_key)
    assert result["valid"] is False
    assert result["checks"] == {"signature": False, "hash": False}
