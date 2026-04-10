"""Ed25519 key loading from environment variables."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)


def derive_key_id(public_key: Ed25519PublicKey) -> str:
    """Derive a stable key ID from the public key: first 16 chars of base64(sha256(der))."""
    der = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    digest = hashlib.sha256(der).digest()
    return base64.b64encode(digest).decode("ascii")[:16]


def load_signing_keys() -> tuple[Ed25519PrivateKey, Ed25519PublicKey, str]:
    """Load Ed25519 keypair from environment variables.

    Expects base64-encoded PEM in INKPRINT_SIGNING_KEY_PRIVATE and
    INKPRINT_SIGNING_KEY_PUBLIC. Raises ValueError on missing or malformed keys.
    """
    priv_b64 = os.environ.get("INKPRINT_SIGNING_KEY_PRIVATE", "")
    pub_b64 = os.environ.get("INKPRINT_SIGNING_KEY_PUBLIC", "")
    key_id = os.environ.get("INKPRINT_KEY_ID", "")

    if not priv_b64 or not pub_b64:
        raise ValueError("INKPRINT_SIGNING_KEY_PRIVATE and INKPRINT_SIGNING_KEY_PUBLIC must be set")

    try:
        priv_pem = base64.b64decode(priv_b64)
        pub_pem = base64.b64decode(pub_b64)
    except Exception as e:
        raise ValueError(f"Failed to decode base64 key: {e}") from e

    private_key = load_pem_private_key(priv_pem, password=None)
    public_key = load_pem_public_key(pub_pem)

    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Private key is not Ed25519")
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("Public key is not Ed25519")

    if not key_id:
        key_id = derive_key_id(public_key)

    return private_key, public_key, key_id
