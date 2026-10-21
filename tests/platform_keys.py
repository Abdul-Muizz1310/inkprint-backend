"""Throwaway Ed25519 keys and platform tokens for the contract-v2 tests (spec 09).

Never a real key: every pair is generated per test run. The formats are the
deployed ones — the public half base64 SPKI DER, as ``BASTION_SIGNING_KEY_PUBLIC``
and ``INKPRINT_FRONTEND_SIGNING_KEY_PUBLIC`` hold it.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_UNSET: Any = object()


@dataclass(frozen=True)
class KeyPair:
    private: Ed25519PrivateKey
    public_b64: str


def keypair() -> KeyPair:
    private = Ed25519PrivateKey.generate()
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return KeyPair(private=private, public_b64=base64.b64encode(der).decode("ascii"))


def bastion_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "bastion",
        "aud": "inkprint",
        "service": "inkprint",
        "sub": "v_abcdef1234",
        "role": "editor",
        "cap": "inkprint.certify",
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
    }
    return _apply(claims, overrides)


def frontend_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "inkprint-frontend",
        "aud": "inkprint",
        "service": "inkprint",
        "sub": "inkprint-frontend",
        "role": "frontend",
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
    }
    return _apply(claims, overrides)


def _apply(claims: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Override claims; pass ``DROP`` to remove one."""
    for name, value in overrides.items():
        if value is DROP:
            claims.pop(name, None)
        else:
            claims[name] = value
    return claims


DROP: Any = object()


def sign(pair: KeyPair, claims: dict[str, Any], *, kid: str = "test-key") -> str:
    return jwt.encode(claims, pair.private, algorithm="EdDSA", headers={"kid": kid})


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def with_payload(token: str, claims: dict[str, Any]) -> str:
    """The same header and signature over a different payload (tampering)."""
    header, _, signature = token.split(".")
    payload = b64url(json.dumps(claims, separators=(",", ":")).encode())
    return f"{header}.{payload}.{signature}"


def unsigned(claims: dict[str, Any]) -> str:
    """An ``alg: none`` token."""
    header = b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = b64url(json.dumps(claims).encode())
    return f"{header}.{payload}."


def hs256_with_public_key(pair: KeyPair, claims: dict[str, Any]) -> str:
    """The classic key-confusion forgery: HMAC keyed with the public key's text."""
    return jwt.encode(claims, pair.public_b64, algorithm="HS256")
